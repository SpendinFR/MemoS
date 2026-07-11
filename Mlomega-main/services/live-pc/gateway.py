from __future__ import annotations

"""V19 live PC video ingress primitives.

The gateway contract is intentionally small: producers expose an async iterator
of ``(frame_bgr, FrameEnvelope)`` and the live stack keeps only the latest frame.
This prevents latent XR backlogs from turning into stale UI overlays.

Two ingress implementations share the ``VideoIngress`` protocol:

* ``IterableIngress`` -- an honest wrapper around any async iterator. Used by unit
  tests and offline bench loops where no real transport is needed.
* ``AiortcIngress`` -- a *real* WebRTC server (aiortc + aiohttp signaling) that
  receives an H.264 video track from a remote peer, decodes it with PyAV, records
  the true decode time in :class:`DecodeBench`, and associates ``FrameEnvelope``
  metadata delivered over a DataChannel with the decoded frames.

Frame/metadata association (documented decision, see docs/DECISIONS.md
"E4/E5 transport reel"): the sender assigns a monotonically increasing
``frame_id`` per encoded frame and sends the matching ``FrameEnvelope`` over the
DataChannel *before* the video frame is pushed. The receiver matches by
``frame_id`` when a pending envelope with the same id exists; otherwise it falls
back to the pending envelope whose ``capture_monotonic_ns`` is closest to the
decoded frame's presentation timestamp. Unmatched frames are still surfaced with
a synthesized placeholder envelope so the queue=1 drop accounting stays honest.

The concrete WebRTC server can be swapped for a GStreamer ``webrtcbin`` +
``nvh264dec`` path without changing downstream consumers, because everything
below only depends on the ``VideoIngress`` protocol.
"""

import asyncio
import inspect
import json
import statistics
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Awaitable, Callable, Protocol

import sys
from pathlib import Path

# Allow ``python services/live-pc/gateway.py`` and importlib-based test loading
# to resolve the ``packages`` namespace from the monorepo root.
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from packages.contracts.python.models import FrameEnvelope, Pose

FramePacket = tuple[Any, FrameEnvelope]

try:  # aiortc is optional: keep the gateway importable without it.
    from aiortc import RTCPeerConnection, RTCSessionDescription
    from aiortc.mediastreams import MediaStreamError

    AIORTC_AVAILABLE = True
except Exception:  # pragma: no cover - exercised only when aiortc missing
    RTCPeerConnection = None  # type: ignore[assignment]
    RTCSessionDescription = None  # type: ignore[assignment]
    MediaStreamError = Exception  # type: ignore[assignment]
    AIORTC_AVAILABLE = False


class VideoIngress(Protocol):
    def __aiter__(self) -> AsyncIterator[FramePacket]: ...


@dataclass
class DecodeBench:
    samples_ms: list[float] = field(default_factory=list)

    def add_ns(self, elapsed_ns: int) -> None:
        self.samples_ms.append(elapsed_ns / 1_000_000)

    def summary(self) -> dict[str, float | int]:
        if not self.samples_ms:
            return {"count": 0, "p50_ms": 0.0, "p95_ms": 0.0}
        ordered = sorted(self.samples_ms)

        def pct(p: float) -> float:
            idx = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * p)))
            return ordered[idx]

        return {"count": len(ordered), "p50_ms": statistics.median(ordered), "p95_ms": pct(0.95)}


class LatestFrameQueue:
    """Single-slot async frame queue with drop accounting (queue = 1)."""

    def __init__(self) -> None:
        self._latest: FramePacket | None = None
        self._event = asyncio.Event()
        self.dropped_frames = 0
        self.received_frames = 0

    def put_latest(self, packet: FramePacket) -> None:
        if self._latest is not None:
            self.dropped_frames += 1
        self._latest = packet
        self.received_frames += 1
        self._event.set()

    async def get_latest(self) -> FramePacket:
        await self._event.wait()
        assert self._latest is not None
        packet = self._latest
        self._latest = None
        self._event.clear()
        return packet

    def stats(self) -> dict[str, int]:
        return {
            "received_frames": self.received_frames,
            "dropped_frames": self.dropped_frames,
            "queue_size": 1 if self._latest else 0,
        }


class IterableIngress:
    """Honest adapter around an async iterator (unit tests, offline benches).

    ``source`` may be any async iterator yielding either ``(frame, envelope)`` or
    objects with ``to_ndarray(format='bgr24')`` plus an ``envelope`` attribute.
    This is *not* a transport: it does no WebRTC and no decoding, it just times
    the (already-decoded) hand-off so the bench numbers stay comparable.
    """

    def __init__(self, source: AsyncIterator[Any]) -> None:
        self.source = source
        self.bench = DecodeBench()

    def __aiter__(self) -> AsyncIterator[FramePacket]:
        return self._iterate()

    async def _iterate(self) -> AsyncIterator[FramePacket]:
        async for item in self.source:
            start = time.perf_counter_ns()
            if isinstance(item, tuple) and len(item) == 2:
                frame_bgr, envelope = item
            else:
                frame_bgr = item.to_ndarray(format="bgr24")
                envelope = item.envelope
            if not isinstance(envelope, FrameEnvelope):
                envelope = FrameEnvelope.model_validate(envelope)
            self.bench.add_ns(time.perf_counter_ns() - start)
            yield frame_bgr, envelope


class _EnvelopeMatcher:
    """Associates DataChannel envelopes with decoded frames.

    Match strategy (see module docstring / DECISIONS.md):
      1. exact ``frame_id`` if the sender embedded it as the frame ordinal;
      2. otherwise the pending envelope whose ``capture_monotonic_ns`` is closest
         to the decoded frame's presentation time (nanoseconds).
    """

    def __init__(self, *, max_pending: int = 512) -> None:
        self._by_id: dict[str, FrameEnvelope] = {}
        self._order: list[str] = []
        self._max_pending = max_pending
        self.matched = 0
        self.fallback_nearest = 0
        self.unmatched = 0

    def add(self, envelope: FrameEnvelope) -> None:
        fid = envelope.frame_id
        if fid not in self._by_id:
            self._order.append(fid)
        self._by_id[fid] = envelope
        while len(self._order) > self._max_pending:
            oldest = self._order.pop(0)
            self._by_id.pop(oldest, None)

    def take(self, *, frame_id: str | None, capture_ns: int | None) -> FrameEnvelope | None:
        if frame_id is not None and frame_id in self._by_id:
            env = self._pop(frame_id)
            self.matched += 1
            return env
        if capture_ns is not None and self._by_id:
            best_id = min(
                self._by_id,
                key=lambda fid: abs(self._by_id[fid].capture_monotonic_ns - capture_ns),
            )
            env = self._pop(best_id)
            self.fallback_nearest += 1
            return env
        self.unmatched += 1
        return None

    # internal helpers -----------------------------------------------------
    def _pop(self, fid: str) -> FrameEnvelope | None:
        env = self._by_id.pop(fid, None)
        try:
            self._order.remove(fid)
        except ValueError:
            pass
        return env

    def stats(self) -> dict[str, int]:
        return {
            "matched": self.matched,
            "fallback_nearest": self.fallback_nearest,
            "unmatched": self.unmatched,
        }


def _placeholder_envelope(session_id: str, frame_id: str, capture_ns: int, source: str) -> FrameEnvelope:
    from datetime import datetime, timezone

    return FrameEnvelope(
        session_id=session_id,
        frame_id=frame_id,
        capture_monotonic_ns=capture_ns,
        captured_at_utc=datetime.now(timezone.utc).isoformat(),
        pose=Pose(position=[0.0, 0.0, 0.0], rotation=[0.0, 0.0, 0.0, 1.0]),
        rotation=0,
        source=source,
        # E37 §5: this is a synthetic neutral pose (no real head tracking on this
        # frame). Mark it so spatial / SceneDelta never treat (0,0,0) as an observed
        # camera pose and pollute the zone cloud / bearings.
        pose_valid=False,
    )


def _audio_frame_to_mono(frame: Any) -> tuple[Any, int]:
    """Convert a PyAV AudioFrame (packed or planar) to mono, preserving scale."""
    import numpy as np

    raw = np.asarray(frame.to_ndarray())
    channels = max(1, len(getattr(getattr(frame, "layout", None), "channels", ()) or ()))
    planar = bool(getattr(getattr(frame, "format", None), "is_planar", False))
    if channels == 1:
        mono = raw.reshape(-1)
    elif planar:
        matrix = raw.reshape(channels, -1)
        if np.issubdtype(raw.dtype, np.integer):
            mono = np.rint(matrix.astype(np.float64).mean(axis=0))
        else:
            mono = matrix.astype(np.float32).mean(axis=0)
    else:
        # PyAV packed s16 stereo is shaped (1, samples * channels).
        matrix = raw.reshape(-1, channels)
        if np.issubdtype(raw.dtype, np.integer):
            mono = np.rint(matrix.astype(np.float64).mean(axis=1))
        else:
            mono = matrix.astype(np.float32).mean(axis=1)
    if np.issubdtype(raw.dtype, np.integer):
        info = np.iinfo(raw.dtype)
        mono = np.clip(mono, info.min, info.max).astype(raw.dtype)
    else:
        mono = mono.astype(np.float32, copy=False)
    return np.ascontiguousarray(mono), int(frame.sample_rate or 48000)


class AiortcIngress:
    """Real WebRTC ingress: aiortc server + aiohttp POST /offer signaling.

    A remote peer (e.g. :mod:`simulators.fake_xr_device`) POSTs an SDP offer to
    ``/offer``; the server answers, receives one video track + one DataChannel,
    decodes each incoming H.264 frame with PyAV, records the real decode time, and
    yields ``(frame_bgr, FrameEnvelope)`` packets. Iterating stops when the peer
    closes the track/connection or ``max_frames`` is reached.
    """

    def __init__(
        self,
        *,
        host: str = "127.0.0.1",
        port: int = 8770,
        session_id: str = "aiortc-ingress",
        source: str = "aiortc_ingress",
        max_frames: int | None = None,
        standalone_signaling: bool = True,
        clip_recorder: Any | None = None,
        audio_queue_max_chunks: int = 3000,
    ) -> None:
        if not AIORTC_AVAILABLE:
            raise RuntimeError("aiortc is not installed; AiortcIngress is unavailable")
        self.host = host
        self.port = port
        self.session_id = session_id
        self.source = source
        self.max_frames = max_frames
        self.standalone_signaling = standalone_signaling
        # E55: optional live clip recorder. None/disabled → offer() is a no-op;
        # it NEVER blocks the live loop (bounded queue, drop-on-full) and NEVER
        # raises. Wired below in _consume_track after the existing bgr24 convert.
        self._clip_recorder = clip_recorder
        self.bench = DecodeBench()
        self.recv_bench = DecodeBench()
        self.matcher = _EnvelopeMatcher()
        # One decoded frame only: stale camera frames are dropped rather than
        # building latency.  Audio has a small bounded queue and is drained by a
        # dedicated worker so ASR never blocks aiortc's receive loop.
        self._frames: asyncio.Queue[FramePacket | None] = asyncio.Queue(maxsize=1)
        # Keep capture independent from ASR/LLM stalls. At the usual 20 ms Opus
        # cadence 3000 chunks retain roughly one minute while using only a few MB.
        # The queue stays bounded; an extreme overrun is explicit in metrics.
        self._audio: asyncio.Queue[tuple[Any, int, dict[str, Any] | None] | None] = asyncio.Queue(
            maxsize=max(32, int(audio_queue_max_chunks))
        )
        self._pcs: set[Any] = set()
        self._offer_lock = asyncio.Lock()
        self._runner: Any | None = None
        self._site: Any | None = None
        self._started = asyncio.Event()
        # Downlink DataChannel(s): the gateway sends UIIntent JSON back to the
        # device over the same reliable/ordered ``contracts`` channel it receives
        # FrameEnvelope/LocalTrack on. ``on_receipt`` is invoked with the raw JSON
        # text of every non-envelope message (UIReceipt) so callers can route it
        # to record_delivery_feedback (delivery_adapter.record_receipt).
        self._channels: set[Any] = set()
        self.on_receipt: Callable[[str], Any] | None = None
        self.on_datachannel_open: Callable[[], Any] | None = None
        self.received_receipts = 0
        self.on_audio_chunk: Callable[[Any, int], Any] | None = None
        self.audio_chunks_received = 0
        self.audio_chunks_dropped = 0
        self.audio_errors = 0
        self.audio_queue_peak = 0
        self.video_frames_dropped = 0
        self.peer_state = "new"
        self._audio_worker: asyncio.Task[Any] | None = None
        self._closed = False
        self._accepting_media = True
        self._audio_inflight = 0
        self._audio_idle = asyncio.Event()
        self._audio_idle.set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._audio_pts_origin_s: float | None = None
        self._audio_wall_origin_s: float | None = None
        self._audio_last_pts_s: float | None = None
        self.last_media_monotonic = time.monotonic()

    def send_ui_intent(self, intent_json: str) -> int:
        """Send a UIIntent (JSON string) to every open downlink DataChannel.

        Returns the number of channels the intent was written to. Non-blocking;
        aiortc buffers on the channel. Safe to call once frames/channel are up.
        """
        loop = self._loop
        if loop is not None:
            try:
                current = asyncio.get_running_loop()
            except RuntimeError:
                current = None
            if current is not loop:
                open_count = sum(1 for c in self._channels if getattr(c, "readyState", None) == "open")
                loop.call_soon_threadsafe(self._send_ui_intent_now, intent_json)
                return open_count
        return self._send_ui_intent_now(intent_json)

    def _send_ui_intent_now(self, intent_json: str) -> int:
        sent = 0
        for channel in list(self._channels):
            try:
                if channel.readyState == "open":
                    channel.send(intent_json)
                    sent += 1
            except Exception:
                self._channels.discard(channel)
        return sent

    @property
    def offer_url(self) -> str:
        return f"http://{self.host}:{self.port}/offer"

    async def start(self) -> None:
        """Start the aiohttp signaling server. Idempotent."""
        self._loop = asyncio.get_running_loop()
        if not self.standalone_signaling:
            self._started.set()
            return
        if self._runner is not None:
            return
        from aiohttp import web

        app = web.Application()
        app.router.add_post("/offer", self._handle_offer)
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, self.host, self.port)
        await self._site.start()
        self._started.set()

    async def wait_started(self) -> None:
        await self._started.wait()

    async def close(self) -> None:
        await self.stop_accepting_media()
        await self.drain_audio(timeout_s=5.0)
        self._closed = True
        coros = [pc.close() for pc in list(self._pcs)]
        self._pcs.clear()
        if coros:
            await asyncio.gather(*coros, return_exceptions=True)
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None
            self._site = None
        await self._replace_latest(self._frames, None)
        await self._audio.put(None)
        if self._audio_worker is not None:
            await asyncio.gather(self._audio_worker, return_exceptions=True)
            self._audio_worker = None

    async def _handle_offer(self, request: Any) -> Any:
        from aiohttp import web

        params = await request.json()
        answer_sdp, answer_type = await self.handle_offer_sdp(params["sdp"], params["type"])
        return web.json_response({"sdp": answer_sdp, "type": answer_type})

    async def handle_offer_sdp(self, sdp: str, sdp_type: str) -> tuple[str, str]:
        """Negotiate one WebRTC peer from a raw SDP offer, return the SDP answer.

        Transport-agnostic core of ``_handle_offer``: used by the ingress' own
        aiohttp ``/offer`` route (backward compatible) *and* by the unified
        ``POST /webrtc/offer`` FastAPI route in ``sessionhub_http`` so
        ``fake_xr_device`` and the Android client share one signaling surface.
        """
        async with self._offer_lock:
            return await self._replace_peer_from_offer(sdp, sdp_type)

    async def _replace_peer_from_offer(self, sdp: str, sdp_type: str) -> tuple[str, str]:
        """Serialize re-offers and close every previous peer before new tracks can
        reset shared PTS/audio state. One transport session owns exactly one peer."""
        self._loop = asyncio.get_running_loop()
        if not self._accepting_media:
            raise RuntimeError("media ingress is frozen")
        previous = list(self._pcs)
        if previous:
            await asyncio.gather(*(self._teardown(old) for old in previous), return_exceptions=True)
        self._channels.clear()
        self._audio_pts_origin_s = None
        self._audio_wall_origin_s = None
        self._audio_last_pts_s = None
        offer = RTCSessionDescription(sdp=sdp, type=sdp_type)
        pc = RTCPeerConnection()
        self._pcs.add(pc)
        self.peer_state = "connecting"

        @pc.on("datachannel")
        def _on_datachannel(channel: Any) -> None:  # noqa: ANN401
            # Register as a downlink so the gateway can push UIIntent JSON back.
            self._channels.add(channel)

            @channel.on("open")
            def _on_open() -> None:
                if self.on_datachannel_open is None:
                    return
                try:
                    result = self.on_datachannel_open()
                    if asyncio.iscoroutine(result):
                        asyncio.create_task(result)
                except Exception:
                    pass

            @channel.on("close")
            def _on_close() -> None:
                self._channels.discard(channel)

            @channel.on("message")
            def _on_message(message: Any) -> None:  # noqa: ANN401
                # Uplink messages are either FrameEnvelope (video metadata) or
                # UIReceipt (device acknowledging a UIIntent). Route by shape:
                # FrameEnvelope carries frame_id + capture_monotonic_ns; UIReceipt
                # carries ui_intent_id + event.
                try:
                    payload = json.loads(message)
                except Exception:
                    return
                if isinstance(payload, dict) and "capture_monotonic_ns" in payload:
                    try:
                        self.matcher.add(FrameEnvelope.model_validate(payload))
                    except Exception:
                        pass
                    return
                # Anything else is treated as a receipt/return channel message.
                self.received_receipts += 1
                if self.on_receipt is not None:
                    try:
                        self.on_receipt(message if isinstance(message, str) else json.dumps(payload))
                    except Exception:
                        pass

        @pc.on("track")
        def _on_track(track: Any) -> None:  # noqa: ANN401
            if track.kind == "video":
                asyncio.ensure_future(self._consume_track(track, pc))
            elif track.kind == "audio":
                if self._audio_worker is None or self._audio_worker.done():
                    self._audio_worker = asyncio.create_task(self._drain_audio())
                asyncio.ensure_future(self._consume_audio_track(track))

        @pc.on("connectionstatechange")
        async def _on_state() -> None:
            self.peer_state = str(pc.connectionState)
            if pc.connectionState in {"failed", "closed", "disconnected"}:
                await self._teardown(pc)

        await pc.setRemoteDescription(offer)
        answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)
        return pc.localDescription.sdp, pc.localDescription.type

    async def _consume_track(self, track: Any, pc: Any) -> None:
        count = 0
        last_ready = time.perf_counter_ns()
        while True:
            if not self._accepting_media:
                break
            try:
                frame = await track.recv()
                self.last_media_monotonic = time.monotonic()
            except MediaStreamError:
                break
            # recv() returns an already-H.264-decoded PyAV frame; the pure decode
            # is not cleanly separable from the jitter-buffer wait in aiortc, so we
            # record two honest signals: (1) bench = the BGR conversion of the
            # decoded frame, (2) recv_bench = inter-frame availability span
            # (decode + jitter buffer + convert), used for the end-to-end number.
            start = time.perf_counter_ns()
            frame_bgr = frame.to_ndarray(format="bgr24")
            now = time.perf_counter_ns()
            self.bench.add_ns(now - start)
            self.recv_bench.add_ns(now - last_ready)
            last_ready = now

            capture_ns: int | None = None
            frame_id: str | None = None
            if frame.pts is not None and frame.time_base is not None:
                capture_ns = int(float(frame.pts * frame.time_base) * 1_000_000_000)

            # E55: hand the already-decoded bgr24 frame to the clip recorder.
            # NON-BLOCKING drop-on-full by construction; a None/disabled recorder
            # is a no-op and any error is swallowed — the live loop below is never
            # slowed, back-pressured, or interrupted by the encoder.
            recorder = self._clip_recorder
            if recorder is not None:
                try:
                    recorder.offer(frame_bgr, capture_ns)
                except Exception:
                    pass
            # aiortc VideoFrames carry no app frame_id; association is by the
            # pending-envelope arrival order (frame_id embedded by sender) and
            # nearest capture timestamp fallback.
            envelope = self.matcher.take(frame_id=frame_id, capture_ns=capture_ns)
            if envelope is None:
                envelope = _placeholder_envelope(
                    self.session_id,
                    f"{self.session_id}-unmatched-{count:06d}",
                    capture_ns if capture_ns is not None else time.monotonic_ns(),
                    self.source,
                )
            await self._replace_latest(self._frames, (frame_bgr, envelope), count_drop=True)
            count += 1
            if self.max_frames is not None and count >= self.max_frames:
                break
        # A track ending is a temporary transport loss.  Do not terminate the
        # ingress iterator: Android's reconnect loop may attach another peer.
        await self._teardown(pc)

    async def _consume_audio_track(self, track: Any) -> None:
        """Convert aiortc/PyAV AudioFrame to interleaved mono PCM + source rate."""
        import numpy as np

        # A reconnect starts a new RTP timeline. Anchor it independently to wall
        # clock so durable BrainLive timestamps never reuse the previous peer PTS.
        self._audio_pts_origin_s = None
        self._audio_wall_origin_s = None
        self._audio_last_pts_s = None
        while not self._closed:
            if not self._accepting_media:
                break
            try:
                frame = await track.recv()
                self.last_media_monotonic = time.monotonic()
            except MediaStreamError:
                break
            try:
                pcm, rate = _audio_frame_to_mono(frame)
                timing = self._audio_source_timing(frame, pcm, rate)
                self.audio_chunks_received += 1
                try:
                    self._audio.put_nowait((pcm, rate, timing))
                    self.audio_queue_peak = max(self.audio_queue_peak, self._audio.qsize())
                except asyncio.QueueFull:
                    self.audio_chunks_dropped += 1
                    try:
                        self._audio.get_nowait()
                        self._audio.task_done()
                    except asyncio.QueueEmpty:
                        pass
                    self._audio.put_nowait((pcm, rate, timing))
            except Exception:
                self.audio_errors += 1

    def _audio_source_timing(self, frame: Any, pcm: Any, rate: int) -> dict[str, Any]:
        """Map the RTP/PyAV media clock to a stable UTC capture window.

        ``pts`` is relative to the peer, not wall-clock. The first frame of each
        audio track anchors that media clock to its receive time minus the frame
        duration; subsequent frames retain their real PTS spacing. Missing or
        discontinuous PTS falls back honestly to the receive clock.
        """
        duration_s = float(len(pcm)) / float(max(1, rate))
        received_end_s = time.time()
        pts_s: float | None = None
        if getattr(frame, "pts", None) is not None and getattr(frame, "time_base", None) is not None:
            try:
                pts_s = float(frame.pts * frame.time_base)
            except (TypeError, ValueError, OverflowError):
                pts_s = None

        discontinuity = (
            pts_s is not None
            and self._audio_last_pts_s is not None
            and (pts_s < self._audio_last_pts_s or (pts_s - self._audio_last_pts_s) > 5.0)
        )
        if pts_s is not None and (
            self._audio_pts_origin_s is None or self._audio_wall_origin_s is None or discontinuity
        ):
            self._audio_pts_origin_s = pts_s
            self._audio_wall_origin_s = received_end_s - duration_s

        if pts_s is not None and self._audio_pts_origin_s is not None and self._audio_wall_origin_s is not None:
            start_s = self._audio_wall_origin_s + (pts_s - self._audio_pts_origin_s)
            self._audio_last_pts_s = pts_s
            source = "webrtc_pts"
        else:
            start_s = received_end_s - duration_s
            source = "receive_clock"
        end_s = start_s + duration_s
        return {
            "absolute_start": datetime.fromtimestamp(start_s, timezone.utc).isoformat(),
            "absolute_end": datetime.fromtimestamp(end_s, timezone.utc).isoformat(),
            "duration_s": duration_s,
            "clock_source": source,
        }

    async def _drain_audio(self) -> None:
        while True:
            item = await self._audio.get()
            if item is None:
                self._audio.task_done()
                return
            callback = self.on_audio_chunk
            pcm, rate = item[0], item[1]
            timing = item[2] if len(item) >= 3 else None
            self._audio_inflight += 1
            self._audio_idle.clear()
            try:
                if callback is not None:
                    args: tuple[Any, ...] = (pcm, rate, timing)
                    try:
                        inspect.signature(callback).bind(*args)
                    except (TypeError, ValueError):
                        # Compatibility for injected/test callbacks written before
                        # source timing became additive to the product contract.
                        args = (pcm, rate)
                    result = await asyncio.to_thread(callback, *args)
                    if asyncio.iscoroutine(result):
                        await result
            except Exception:
                self.audio_errors += 1
            finally:
                self._audio_inflight -= 1
                self._audio.task_done()
                if self._audio_inflight == 0:
                    self._audio_idle.set()

    async def stop_accepting_media(self) -> None:
        """Freeze this ingress and stop all current peer producers."""
        self._accepting_media = False
        self.peer_state = "ending"
        peers = list(self._pcs)
        if peers:
            await asyncio.gather(*(self._teardown(pc) for pc in peers), return_exceptions=True)

    async def drain_audio(self, *, timeout_s: float = 5.0) -> None:
        """Wait for queued and currently executing audio callbacks."""
        async def _wait() -> None:
            await self._audio.join()
            await self._audio_idle.wait()
        await asyncio.wait_for(_wait(), timeout=timeout_s)

    async def _replace_latest(self, queue: Any, item: Any, *, count_drop: bool = False) -> None:
        if queue.full():
            try:
                queue.get_nowait()
                if count_drop:
                    self.video_frames_dropped += 1
            except asyncio.QueueEmpty:
                pass
        queue.put_nowait(item)

    def stats(self) -> dict[str, Any]:
        return {
            "peer_state": self.peer_state,
            "frames_received": len(self.bench.samples_ms),
            "frames_dropped": self.video_frames_dropped,
            "audio_chunks_received": self.audio_chunks_received,
            "audio_chunks_dropped": self.audio_chunks_dropped,
            "audio_errors": self.audio_errors,
            "audio_queue_depth": self._audio.qsize(),
            "audio_queue_peak": self.audio_queue_peak,
            "audio_inflight": self._audio_inflight,
            "accepting_media": self._accepting_media,
            "media_idle_seconds": max(0.0, time.monotonic() - self.last_media_monotonic),
        }

    async def _teardown(self, pc: Any) -> None:
        if pc in self._pcs:
            self._pcs.discard(pc)
            try:
                await pc.close()
            except Exception:
                pass

    def __aiter__(self) -> AsyncIterator[FramePacket]:
        return self._iterate()

    async def _iterate(self) -> AsyncIterator[FramePacket]:
        await self.start()
        while True:
            packet = await self._frames.get()
            if packet is None:
                break
            yield packet


async def pump_latest(
    ingress: VideoIngress, queue: LatestFrameQueue, *, limit: int | None = None
) -> dict[str, Any]:
    count = 0
    async for packet in ingress:
        queue.put_latest(packet)
        count += 1
        if limit is not None and count >= limit:
            break
    return queue.stats()
