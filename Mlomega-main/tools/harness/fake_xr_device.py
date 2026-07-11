from __future__ import annotations

"""E63 end-to-end integration harness: a complete fake XR device.

This is a NEW, self-contained WebRTC client that replays a full session against
the REAL PC code (services/live-pc/sessionhub_http.py + phoneonly_runtime.py).
It is a pure NETWORK CLIENT: it never imports the product modules for the live
flow. It speaks exactly the wire protocol the Android LiveTransportPlugin speaks:

  1. HTTP pairing against SessionHub:
       POST /session/create  {device_id}          -> {session_id, token, ...}
  2. WebRTC negotiation through the unified signaling endpoint:
       POST /webrtc/offer     {sdp, type, session_id, token} -> {sdp, type}
     pushing a real audio track + a real video track from an MP4
     (aiortc MediaPlayer, native real-time pacing) plus a reliable DataChannel.
  3. Over the DataChannel it sends, matching the exact schemas copied from the
     Unity client (do NOT guess field names):
       * FrameEnvelope  (contracts/python/models.py + FrameEnvelope.cs): the
         video metadata; the gateway routes any message carrying
         ``capture_monotonic_ns`` to the envelope matcher.
       * device_command_result  (DeviceCommandHandler.SendCommandResult): the ack
         the PC's phoneonly_runtime._on_receipt awaits after push_wake_word() sends
         a ``set_wake_word`` device_command on DataChannel open.
       * device_transcript  (LiveTransportBridge.SendTranscriptSegment): a final
         ASR segment, optionally tagged ``is_command`` so the PC IntentRouter
         routes it (on_device_transcript). This is how the scripted intents are
         delivered.
  4. A scripted SCENARIO: an ordered list of (t_seconds, message) events replayed
     on the DataChannel, then a clean end of session:
       POST /session/end  {session_id, token}     -> triggers close-day.

CLI (see tools/harness/README.md for copy-paste commands):
  --host / --port     SessionHub HTTP endpoint (default 127.0.0.1:8730)
  --media <mp4>       MP4 to replay; if absent, a 60s synthetic mire+bip is built
  --scenario <json>   scenario file (default scenarios/basic_session.json)
  --duration <s>      hard cap on the media/session duration
  --session-id        override the device_id used for pairing
  --end-session / --no-end-session   whether to POST /session/end at the end
  --out <json>        write the final device-side report (paired ids, counts)

Nothing here mutates any existing product file. New file only.
"""

import argparse
import asyncio
import json
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiohttp
from aiortc import RTCPeerConnection, RTCSessionDescription
from aiortc.contrib.media import MediaPlayer

HERE = Path(__file__).resolve().parent
DEFAULT_SCENARIO = HERE / "scenarios" / "basic_session.json"


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def synth_media_mp4(dst: Path, *, duration: int = 60) -> Path:
    """Build a synthetic MP4 (moving test pattern + beep tone) via ffmpeg.

    Uses only ffmpeg's built-in lavfi sources (testsrc + sine), so no product
    asset is needed. The audio track is what the PC ASR/audio-archive consumes;
    the video track feeds vision/clip-recorder. Real content is not required for
    the transport/DB assertions -- only that both tracks flow.
    """
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise RuntimeError("ffmpeg not found on PATH; pass --media <mp4> instead")
    dst.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg, "-y",
        "-f", "lavfi", "-i", f"testsrc=size=1280x720:rate=15:duration={duration}",
        "-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=48000:duration={duration}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "ultrafast",
        "-c:a", "aac", "-shortest",
        str(dst),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0 or not dst.exists():
        raise RuntimeError(f"ffmpeg synth failed: {(proc.stderr or '')[-1500:]}")
    return dst


class FakeXrDevice:
    """A full fake XR device driving the real PC over WebRTC."""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        media: Path,
        scenario: list[dict[str, Any]],
        device_id: str,
        duration: float | None = None,
        end_session: bool = True,
        frame_hz: float = 10.0,
    ) -> None:
        self.base_url = f"http://{host}:{port}"
        self.media = media
        self.scenario = scenario
        self.device_id = device_id
        self.duration = duration
        self.end_session = end_session
        self.frame_hz = frame_hz

        self.session_id: str | None = None
        self.token: str | None = None
        self.report: dict[str, Any] = {
            "device_id": device_id,
            "envelopes_sent": 0,
            "scenario_events_sent": 0,
            "device_commands_received": 0,
            "wake_word_acked": False,
            "downlink_messages": 0,
            "end_session_status": None,
            "errors": [],
        }
        self._channel: Any = None
        self._pc: RTCPeerConnection | None = None
        self._frame_task: asyncio.Task[Any] | None = None
        self._stop = asyncio.Event()

    # -- pairing ------------------------------------------------------------
    async def _pair(self, http: aiohttp.ClientSession) -> None:
        async with http.post(
            f"{self.base_url}/session/create", json={"device_id": self.device_id}
        ) as resp:
            resp.raise_for_status()
            creds = await resp.json()
        self.session_id = creds["session_id"]
        self.token = creds["token"]
        self.report["session_id"] = self.session_id

    async def _wait_pairing_ready(self, http: aiohttp.ClientSession, *, timeout_s: float = 60.0) -> dict[str, Any]:
        """Poll /health until the server reports pairing_ready (recovery done)."""
        deadline = time.monotonic() + timeout_s
        last: dict[str, Any] = {}
        while time.monotonic() < deadline:
            try:
                async with http.get(f"{self.base_url}/health") as resp:
                    last = await resp.json()
                if last.get("pairing_ready"):
                    return last
            except Exception as exc:  # server still coming up
                last = {"error": type(exc).__name__}
            await asyncio.sleep(1.0)
        return last

    # -- DataChannel senders ------------------------------------------------
    def _send(self, payload: dict[str, Any]) -> bool:
        ch = self._channel
        if ch is None or ch.readyState != "open":
            return False
        ch.send(json.dumps(payload))
        return True

    def _make_envelope(self, idx: int) -> dict[str, Any]:
        # Exact schema: packages/contracts/python/models.py FrameEnvelope +
        # FrameEnvelope.cs. A static, valid forward-facing pose (pose_valid True).
        return {
            "session_id": self.session_id,
            "frame_id": f"{self.session_id}-frame-{idx:06d}",
            "capture_monotonic_ns": time.monotonic_ns(),
            "captured_at_utc": _utc(),
            "pose": {"position": [0.0, 0.0, 0.0], "rotation": [0.0, 0.0, 0.0, 1.0]},
            "pose_valid": True,
            "rotation": 0,
            "source": "fake_xr_device",
        }

    def _device_transcript(self, event: dict[str, Any], seq: int) -> dict[str, Any]:
        # Exact schema: LiveTransportBridge.SendTranscriptSegment.
        text = str(event.get("text") or "")
        start_ms = int(event.get("start_ms", seq * 1000))
        end_ms = int(event.get("end_ms", start_ms + 900))
        return {
            "type": "device_transcript",
            "segment_id": f"device:{start_ms}:{end_ms}",
            "text": text,
            "language": str(event.get("language", "fr")),
            "start_ms": start_ms,
            "end_ms": end_ms,
            "is_final": True,
            "is_command": bool(event.get("is_command", True)),
        }

    # -- downlink handler (PC -> device) ------------------------------------
    def _on_downlink(self, raw: Any) -> None:
        self.report["downlink_messages"] += 1
        try:
            payload = json.loads(raw)
        except Exception:
            return
        if not isinstance(payload, dict):
            return
        # A device_command arrives from the PC IntentRouter / wake-word push.
        # DeviceCommand.IsDeviceCommand keys on the literal "device_command".
        if payload.get("type") == "device_command":
            self.report["device_commands_received"] += 1
            action = payload.get("action")
            # Ack with device_command_result (DeviceCommandHandler.SendCommandResult).
            self._send({
                "type": "device_command_result",
                "command_id": payload.get("command_id"),
                "action": action,
                "ok": True,
            })
            if action == "set_wake_word":
                self.report["wake_word_acked"] = True

    # -- frame envelope pump (paces alongside the native media track) -------
    async def _pump_envelopes(self) -> None:
        idx = 0
        period = 1.0 / self.frame_hz if self.frame_hz > 0 else 0.1
        while not self._stop.is_set():
            if self._send(self._make_envelope(idx)):
                idx += 1
                self.report["envelopes_sent"] = idx
            await asyncio.sleep(period)

    # -- scenario replay ----------------------------------------------------
    async def _play_scenario(self) -> None:
        start = time.monotonic()
        for seq, event in enumerate(self.scenario):
            t = float(event.get("t", 0.0))
            wait = start + t - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            if self._stop.is_set():
                break
            kind = event.get("kind", "transcript")
            if kind == "transcript":
                sent = self._send(self._device_transcript(event, seq))
            elif kind == "device_intent":
                # Menu-driven action path (DeviceCommandHandler.ExecuteFromMenu).
                sent = self._send({
                    "type": "device_intent",
                    "action": str(event.get("action") or ""),
                    "time": event.get("time"),
                })
            elif kind == "raw":
                sent = self._send(dict(event.get("payload") or {}))
            else:
                sent = False
            if sent:
                self.report["scenario_events_sent"] += 1

    # -- lifecycle ----------------------------------------------------------
    async def run(self) -> dict[str, Any]:
        async with aiohttp.ClientSession() as http:
            health = await self._wait_pairing_ready(http)
            self.report["health"] = {
                "pairing_ready": health.get("pairing_ready"),
                "ai_ready": health.get("ai_ready"),
                "status": health.get("status"),
            }
            await self._pair(http)

            pc = RTCPeerConnection()
            self._pc = pc
            channel = pc.createDataChannel("contracts", ordered=True)
            self._channel = channel
            opened = asyncio.Event()

            @channel.on("open")
            def _on_open() -> None:
                opened.set()

            @channel.on("message")
            def _on_message(message: Any) -> None:
                self._on_downlink(message)

            player = MediaPlayer(str(self.media))
            if player.audio is not None:
                pc.addTrack(player.audio)
            if player.video is not None:
                pc.addTrack(player.video)

            @pc.on("connectionstatechange")
            async def _on_state() -> None:
                self.report["peer_state"] = pc.connectionState
                if pc.connectionState in {"failed", "closed", "disconnected"}:
                    self._stop.set()

            offer = await pc.createOffer()
            await pc.setLocalDescription(offer)
            async with http.post(
                f"{self.base_url}/webrtc/offer",
                json={
                    "sdp": pc.localDescription.sdp,
                    "type": pc.localDescription.type,
                    "session_id": self.session_id,
                    "token": self.token,
                },
            ) as resp:
                resp.raise_for_status()
                answer = await resp.json()
            await pc.setRemoteDescription(
                RTCSessionDescription(sdp=answer["sdp"], type=answer["type"])
            )

            try:
                await asyncio.wait_for(opened.wait(), timeout=15.0)
            except asyncio.TimeoutError:
                self.report["errors"].append("datachannel never opened")

            self._frame_task = asyncio.create_task(self._pump_envelopes())
            scenario_task = asyncio.create_task(self._play_scenario())

            # Let the media play out for the scenario span (+ tail), capped by
            # --duration when given.
            scenario_end = max((float(e.get("t", 0.0)) for e in self.scenario), default=0.0)
            budget = self.duration if self.duration is not None else scenario_end + 5.0
            try:
                await asyncio.wait_for(scenario_task, timeout=budget + 5.0)
            except asyncio.TimeoutError:
                pass
            remaining = budget - (max(0.0, scenario_end))
            if remaining > 0:
                await asyncio.sleep(min(remaining, budget))

            self._stop.set()
            if self._frame_task is not None:
                self._frame_task.cancel()
                await asyncio.gather(self._frame_task, return_exceptions=True)

            # Clean end of session -> triggers close-day on the PC.
            if self.end_session:
                try:
                    async with http.post(
                        f"{self.base_url}/session/end",
                        json={"session_id": self.session_id, "token": self.token},
                    ) as resp:
                        status = await resp.json()
                    self.report["end_session_status"] = (
                        status.get("end_session") if isinstance(status, dict) else status
                    )
                    self.report["end_session_full"] = status if isinstance(status, dict) else None
                except Exception as exc:
                    self.report["errors"].append(f"end_session: {type(exc).__name__}: {exc}")

            try:
                await player.audio.stop() if player.audio else None
            except Exception:
                pass
            await pc.close()
        return self.report


def load_scenario(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        return list(data.get("events") or [])
    return list(data)


async def _amain(args: argparse.Namespace) -> int:
    if args.media:
        media = Path(args.media)
        if not media.exists():
            print(json.dumps({"error": f"media not found: {media}"}))
            return 2
    else:
        synth_dir = Path(args.synth_dir) if args.synth_dir else HERE / "_synth"
        media = synth_media_mp4(synth_dir / "harness_media.mp4", duration=int(args.synth_seconds))

    scenario = load_scenario(Path(args.scenario))
    device = FakeXrDevice(
        host=args.host,
        port=args.port,
        media=media,
        scenario=scenario,
        device_id=args.session_id,
        duration=args.duration,
        end_session=args.end_session,
    )
    report = await device.run()
    text = json.dumps(report, indent=2)
    print(text)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    return 0 if not report.get("errors") else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="E63 fake XR device (real WebRTC client)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8730)
    parser.add_argument("--media", help="MP4 to replay (else a synthetic mire+bip is built)")
    parser.add_argument("--scenario", default=str(DEFAULT_SCENARIO))
    parser.add_argument("--duration", type=float, default=None, help="hard cap seconds")
    parser.add_argument("--session-id", dest="session_id", default="e63-harness")
    parser.add_argument("--end-session", dest="end_session", action="store_true", default=True)
    parser.add_argument("--no-end-session", dest="end_session", action="store_false")
    parser.add_argument("--synth-seconds", type=int, default=60)
    parser.add_argument("--synth-dir", default=None)
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)
    return asyncio.run(_amain(args))


if __name__ == "__main__":
    sys.exit(main())
