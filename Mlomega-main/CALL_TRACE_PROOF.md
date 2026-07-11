# V4 Call Trace Proof

Scope: clean V4 merge of the V3.2 static call trace and the verified E53/E58/E59/E60 session changes dated 2026-07-10. Existing line references come from the V3.2 checkout scan; newly merged E53–E60 paths are recorded at symbol/path level because the source checkout itself was not included with these artefacts. Android hardware, Unity build and real phone-to-PC validation remain unclaimed unless explicitly proven.

Git status captured by the V3.2 source scan before the original artefacts were written:

```text
?? Oldconversation/
?? REPO_MAP.md
?? apps/xr-mobile/editmode-e48.xml
?? repo_graph.json
```

Proof status:

- `proven`: direct call edges are visible and an existing test traverses the same important code path.
- `partially_proven`: the code path is wired in current source and partly tested, but one or more runtime boundaries remain unproven, usually Android/JNI/WebRTC hardware.
- `to_verify`: no direct caller/test proves the link; the path is only implied, dynamic, optional, or operational.

Boundary proof levels:

- `static_direct`: caller/callee visible in source at the cited line.
- `http_boundary`: route or HTTP client visible; full network runtime may still be untested.
- `jni_boundary`: Unity `AndroidJavaObject`/Kotlin bridge visible; requires Android build/device for runtime proof.
- `webrtc_boundary`: aiortc/WebRTC callback visible; actual browser/Android media negotiation may still be untested.
- `datachannel_boundary`: DataChannel send/receive visible; actual device link may still be untested.
- `db_boundary`: table read/write visible in SQL/upsert.

## 01. PhoneOnly pairing

status: `partially_proven`

objective: Android chooses a real PC endpoint, creates/renews a SessionHub session, clock-syncs, and exposes session_id/token to transport.

real entry:

- `apps/xr-mobile/Assets/Scripts/Core/SessionPairing.cs:77` `SessionPairing.OnEnable()`.

call trace:

- `SessionPairing.OnEnable()` -> `StartCoroutine(Lifecycle())` at `apps/xr-mobile/Assets/Scripts/Core/SessionPairing.cs:88`. Payload: assigned `MLOmegaConfig`.
- `SessionPairing.Lifecycle()` -> `ResolveActiveEndpoint()` at `apps/xr-mobile/Assets/Scripts/Core/SessionPairing.cs:169`. Payload: `MLOmegaConfig.ResolvedEndpoints`.
- `ResolveActiveEndpoint()` -> `GET ep.HealthUrl` via `UnityWebRequest.Get()` at `apps/xr-mobile/Assets/Scripts/Core/SessionPairing.cs:121` and `apps/xr-mobile/Assets/Scripts/Core/SessionPairing.cs:125`. Boundary: `http_boundary`.
- `ResolveActiveEndpoint()` -> `new SessionHubClient(ep.BaseUrl, ...)` at `apps/xr-mobile/Assets/Scripts/Core/SessionPairing.cs:142`. Payload: selected LAN/Tailscale base URL.
- `SessionPairing.Lifecycle()` -> `_hub.CreateSession(_config.DeviceId, ...)` at `apps/xr-mobile/Assets/Scripts/Core/SessionPairing.cs:210`.
- `SessionHubClient.CreateSession()` -> `POST /session/create` at `apps/xr-mobile/Assets/Scripts/Core/SessionHubClient.cs:62` and `apps/xr-mobile/Assets/Scripts/Core/SessionHubClient.cs:63`. Payload: `{device_id}`.
- PC route `POST /session/create` -> `hub.create_session(device_id)` at `services/live-pc/sessionhub_http.py:296` and `services/live-pc/sessionhub_http.py:302`. Payload returned: `session_id`, `token`, `created_at_utc`, `expires_at_utc`, `expires_in_seconds` at `services/live-pc/sessionhub_http.py:303`.
- Steady state token renewal: `SessionPairing.Lifecycle()` -> `RenewOnce()` at `apps/xr-mobile/Assets/Scripts/Core/SessionPairing.cs:247` and `apps/xr-mobile/Assets/Scripts/Core/SessionPairing.cs:249`.
- `SessionPairing.RenewOnce()` -> `_hub.RenewToken(SessionId, Token, ...)` at `apps/xr-mobile/Assets/Scripts/Core/SessionPairing.cs:273`. Payload: `{session_id, token}`.
- `SessionHubClient.RenewToken()` -> `POST /session/renew` at `apps/xr-mobile/Assets/Scripts/Core/SessionHubClient.cs:80` and `apps/xr-mobile/Assets/Scripts/Core/SessionHubClient.cs:81`.
- Clock sync: `SessionPairing.Lifecycle()` -> `Clock.RunBurst(SessionId, Token)` at `apps/xr-mobile/Assets/Scripts/Core/SessionPairing.cs:253` and `apps/xr-mobile/Assets/Scripts/Core/SessionPairing.cs:255`, then HTTP transport calls `SessionHubClient.ClockSync()` at `apps/xr-mobile/Assets/Scripts/Core/SessionHubClient.cs:182` and `apps/xr-mobile/Assets/Scripts/Core/SessionHubClient.cs:185`.
- PC clock route `POST /session/clock-sync` authenticates at `services/live-pc/sessionhub_http.py:331`, `services/live-pc/sessionhub_http.py:342`, stamps with `hub.begin_clock_sync()` at `services/live-pc/sessionhub_http.py:349`, mirrors `hub.complete_clock_sync()` at `services/live-pc/sessionhub_http.py:356`.

tables read/write: none; `SessionHub` stores sessions/tokens in memory. TTL is real in `services/live-pc/sessionhub.py:31`, token expiry fields at `services/live-pc/sessionhub.py:57` and purge at `services/live-pc/sessionhub.py:104`.

tests existing:

- `tests/v19/test_sessionhub_http.py:77` create response.
- `tests/v19/test_sessionhub_http.py:176` renew rotates token and revokes old.
- `tests/v19/test_sessionhub_http.py:207` expired token/session purge.
- `apps/xr-mobile/Assets/Tests/EditMode/ClockSyncTests.cs:13` C# clock math fixture.

tests missing:

- Android device endpoint failover from LAN to Tailscale with `SessionPairing.ActiveBaseUrl` observed.

command:

```powershell
.\.venv-live\Scripts\python.exe -m pytest tests/v19/test_sessionhub_http.py tests/v19/test_sessionhub.py
```

risks if modified:

- Accepting any HTTP 200 as healthy in Unity is only safe because PC `/health` returns 503 when not PhoneOnly-ready (`services/live-pc/sessionhub_http.py:226` to `services/live-pc/sessionhub_http.py:240`).
- `turns` must not gain `created_at`; unrelated schema changes here must not touch V18 turn invariants.

## 02. WebRTC setup

status: `partially_proven`

objective: Paired Android starts Kotlin WebRTC transport, posts SDP offer to SessionHub, creates a PhoneOnly runtime, and negotiates aiortc.

real entry:

- `apps/xr-mobile/Assets/Scripts/Transport/PhoneOnlySessionCoordinator.cs:49` `OnPairingStateChanged(Paired)`.

call trace:

- `PhoneOnlySessionCoordinator.OnPairingStateChanged()` -> `TryStartTransport()` at `apps/xr-mobile/Assets/Scripts/Transport/PhoneOnlySessionCoordinator.cs:49` and `apps/xr-mobile/Assets/Scripts/Transport/PhoneOnlySessionCoordinator.cs:51`.
- `TryStartTransport()` checks paired + running + `PhoneOnlyAdapter`, then `_transport.StartTransport()` at `apps/xr-mobile/Assets/Scripts/Transport/PhoneOnlySessionCoordinator.cs:65` to `apps/xr-mobile/Assets/Scripts/Transport/PhoneOnlySessionCoordinator.cs:72`.
- `LiveTransportBridge.StartTransport()` -> Android-only `StartAndroid()` at `apps/xr-mobile/Assets/Scripts/Transport/LiveTransportBridge.cs:126` to `apps/xr-mobile/Assets/Scripts/Transport/LiveTransportBridge.cs:134`. Boundary: `jni_boundary`. Editor path logs no-op at `apps/xr-mobile/Assets/Scripts/Transport/LiveTransportBridge.cs:135` to `apps/xr-mobile/Assets/Scripts/Transport/LiveTransportBridge.cs:138`.
- `StartAndroid()` builds WebRTC offer URL from `_pairing.ActiveBaseUrl.TrimEnd('/') + "/webrtc/offer"` at `apps/xr-mobile/Assets/Scripts/Transport/LiveTransportBridge.cs:263` to `apps/xr-mobile/Assets/Scripts/Transport/LiveTransportBridge.cs:267`.
- `StartAndroid()` constructs `LiveTransportPlugin` and calls native `start()` at `apps/xr-mobile/Assets/Scripts/Transport/LiveTransportBridge.cs:279` to `apps/xr-mobile/Assets/Scripts/Transport/LiveTransportBridge.cs:282`.
- Kotlin `LiveTransportPlugin` creates the ordered `contracts` DataChannel at `apps/xr-mobile/android/livetransport/src/main/java/com/mlomega/xr/livetransport/LiveTransportPlugin.kt:303` to `apps/xr-mobile/android/livetransport/src/main/java/com/mlomega/xr/livetransport/LiveTransportPlugin.kt:307`.
- Kotlin adds audio/video tracks at `apps/xr-mobile/android/livetransport/src/main/java/com/mlomega/xr/livetransport/LiveTransportPlugin.kt:309` and `apps/xr-mobile/android/livetransport/src/main/java/com/mlomega/xr/livetransport/LiveTransportPlugin.kt:310`.
- Kotlin creates SDP offer at `apps/xr-mobile/android/livetransport/src/main/java/com/mlomega/xr/livetransport/LiveTransportPlugin.kt:313`, applies Opus config at `apps/xr-mobile/android/livetransport/src/main/java/com/mlomega/xr/livetransport/LiveTransportPlugin.kt:320`, then `SignalingClient.exchangeOffer()` at `apps/xr-mobile/android/livetransport/src/main/java/com/mlomega/xr/livetransport/LiveTransportPlugin.kt:328` to `apps/xr-mobile/android/livetransport/src/main/java/com/mlomega/xr/livetransport/LiveTransportPlugin.kt:331`.
- `SignalingClient.exchangeOffer()` sends `{sdp,type,session_id,token}` at `apps/xr-mobile/android/livetransport/src/main/java/com/mlomega/xr/livetransport/SignalingClient.kt:93` to `apps/xr-mobile/android/livetransport/src/main/java/com/mlomega/xr/livetransport/SignalingClient.kt:99`; POST target is `ep.webrtcOfferUrl` at `apps/xr-mobile/android/livetransport/src/main/java/com/mlomega/xr/livetransport/SignalingClient.kt:111` to `apps/xr-mobile/android/livetransport/src/main/java/com/mlomega/xr/livetransport/SignalingClient.kt:113`.
- PC `POST /webrtc/offer` route starts at `services/live-pc/sessionhub_http.py:372`, authenticates at `services/live-pc/sessionhub_http.py:385`, calls `manager.get_or_create(session_id)` at `services/live-pc/sessionhub_http.py:387` to `services/live-pc/sessionhub_http.py:390`, and calls `active.handle_offer_sdp(sdp, sdp_type)` at `services/live-pc/sessionhub_http.py:401`.
- `SinglePhoneRuntimeManager.get_or_create()` constructs runtime and `await self.active.start()` at `services/live-pc/phoneonly_runtime.py:333` to `services/live-pc/phoneonly_runtime.py:348`.
- `PhoneOnlyRuntime.start()` launches `self.pipeline.run_video()` at `services/live-pc/phoneonly_runtime.py:119` to `services/live-pc/phoneonly_runtime.py:123`.
- `AiortcIngress.handle_offer_sdp()` creates `RTCPeerConnection`, datachannel handler, track handler at `services/live-pc/gateway.py:403` to `services/live-pc/gateway.py:463`. Boundary: `webrtc_boundary`.

tables read/write: none during signaling; runtime creation may create BrainLive session through `ConversationBridge.ensure_session()` before media flows.

tests existing:

- `tests/v19/test_phoneonly_runtime.py:175` offer creates runtime and authenticated end path.
- `tests/v19/test_transport_webrtc.py:149` `/webrtc/offer` through SessionHub delivers frames.
- `tests/v19/test_phoneonly_android_wiring.py:21` static Android auth/ICE/teardown wiring.

tests missing:

- Real Android Kotlin `LiveTransportPlugin.start()` against PC `/webrtc/offer`.

command:

```powershell
.\.venv-live\Scripts\python.exe -m pytest tests/v19/test_phoneonly_runtime.py::test_offer_creates_runtime_and_end_is_authenticated tests/v19/test_transport_webrtc.py::test_webrtc_offer_through_sessionhub_http_delivers_frames
```

risks if modified:

- Reintroducing `Config.WebrtcOfferUrl` before `ActiveBaseUrl` would break LAN/Tailscale failover; current static proof uses active endpoint at `LiveTransportBridge.cs:263` to `LiveTransportBridge.cs:267`.
- A singleton `app.state.ingress` must not overwrite a different live phone; current manager refuses second active session at `services/live-pc/phoneonly_runtime.py:335` to `services/live-pc/phoneonly_runtime.py:340`.

## 03. Live audio

status: `partially_proven`

objective: Android microphone becomes WebRTC Opus audio, aiortc receives audio track, converts AudioFrame to PCM mono + source rate, feeds `LivePipeline.on_audio_chunk()`, final transcripts reach BrainLive and WAV archive.

real entry:

- Kotlin WebRTC mic track: `apps/xr-mobile/android/livetransport/src/main/java/com/mlomega/xr/livetransport/LiveTransportPlugin.kt:361` `addAudioTrack()`.
- PC aiortc callback: `services/live-pc/gateway.py:463` `@pc.on("track")`.

call trace:

- Kotlin creates WebRTC audio device module from `JavaAudioDeviceModule.builder(appContext)` at `apps/xr-mobile/android/livetransport/src/main/java/com/mlomega/xr/livetransport/LiveTransportPlugin.kt:176` and audio source `VOICE_RECOGNITION` at `apps/xr-mobile/android/livetransport/src/main/java/com/mlomega/xr/livetransport/LiveTransportPlugin.kt:177`. Boundary: Android mic/JNI.
- Kotlin samples-ready callback fans the same captured PCM to on-device ASR at `apps/xr-mobile/android/livetransport/src/main/java/com/mlomega/xr/livetransport/LiveTransportPlugin.kt:180` to `apps/xr-mobile/android/livetransport/src/main/java/com/mlomega/xr/livetransport/LiveTransportPlugin.kt:188`. Payload: PCM16 bytes, sampleRate, channelCount, timestampMs.
- Kotlin creates the WebRTC audio track `mic0` and `pc.addTrack(track, ...)` at `apps/xr-mobile/android/livetransport/src/main/java/com/mlomega/xr/livetransport/LiveTransportPlugin.kt:371` to `apps/xr-mobile/android/livetransport/src/main/java/com/mlomega/xr/livetransport/LiveTransportPlugin.kt:375`.
- PC WebRTC track handler branches `track.kind == "audio"` at `services/live-pc/gateway.py:463` to `services/live-pc/gateway.py:470` and schedules `_consume_audio_track(track)`.
- `_consume_audio_track()` awaits `track.recv()` at `services/live-pc/gateway.py:539` to `services/live-pc/gateway.py:547`.
- `_consume_audio_track()` -> `_audio_frame_to_mono(frame)` at `services/live-pc/gateway.py:551`. Payload: PyAV `AudioFrame`.
- `_audio_frame_to_mono()` calls `frame.to_ndarray()` and derives mono/rate at `services/live-pc/gateway.py:226` to `services/live-pc/gateway.py:253`. Output: contiguous mono array + `frame.sample_rate or 48000`.
- `_consume_audio_track()` queues `(pcm, rate)` non-blocking with drop-oldest on full at `services/live-pc/gateway.py:553` to `services/live-pc/gateway.py:562`.
- `_drain_audio()` calls callback in a worker thread at `services/live-pc/gateway.py:566` to `services/live-pc/gateway.py:579`.
- `PhoneOnlyRuntime.__init__()` wires `ingress.on_audio_chunk = self._on_audio_chunk` at `services/live-pc/phoneonly_runtime.py:98`.
- `PhoneOnlyRuntime._on_audio_chunk()` -> `self.pipeline.on_audio_chunk(samples, src_rate)` at `services/live-pc/phoneonly_runtime.py:184` to `services/live-pc/phoneonly_runtime.py:187`.
- `LivePipeline.on_audio_chunk()` -> `self.audio.push_audio(samples, src_rate)` at `services/live-pc/live_pipeline.py:1080` to `services/live-pc/live_pipeline.py:1081`.
- `AudioRT.push_audio()` -> VAD segments -> `_handle_segment()` at `services/live-pc/audiort.py:358` to `services/live-pc/audiort.py:365`.
- `AudioRT._handle_segment()` -> transcriber, final UIIntent, on-segment callback at `services/live-pc/audiort.py:379` to `services/live-pc/audiort.py:427`.
- `LivePipeline._on_audio_segment()` writes WAV and archives segment through `audio_archive.archive_segment()` at `services/live-pc/live_pipeline.py:1044` to `services/live-pc/live_pipeline.py:1068`.
- Final transcripts enter `ConversationBridge.ingest_segment()` at `services/live-pc/live_pipeline.py:1162` to `services/live-pc/live_pipeline.py:1171`.
- `ConversationBridge.ingest_segment()` -> `ingest_live_turn()` at `services/live-pc/conversation_bridge.py:177` to `services/live-pc/conversation_bridge.py:191`.

tables read/write:

- Writes `brainlive_sensor_events` through `AudioArchive._write_event()` at `services/live-pc/audio_archive.py:348` to `services/live-pc/audio_archive.py:360`.
- Writes `brainlive_audio_segments_v154` immediately after `_write_event()`; entry point is `services/live-pc/audio_archive.py:281`.
- Writes BrainLive live turn buffer via `ingest_live_turn()` from `services/live-pc/conversation_bridge.py:177`.

tests existing:

- `tests/v19/test_phoneonly_runtime.py:222` audio frame conversion reaches PCM callback.
- `tests/v19/test_phoneonly_runtime.py:315` explicit end waits for inflight audio before flush/end.
- `tests/v19/test_phoneonly_runtime.py:350` VAD segment archives even when ASR unavailable.
- `tests/v19/test_e31_conversation.py:69` final segment reaches core turn buffer.
- `apps/xr-mobile/android/livetransport/src/test/java/com/mlomega/xr/livetransport/MicAudioFanoutTest.kt:61` PCM fan-out delivers same samples.

tests missing:

- Hardware proof: Android microphone -> Opus track -> aiortc audio track -> PCM -> AudioRT with real device.
- Full final transcript proof with real faster-whisper + phone audio, not injected frames.

command:

```powershell
.\.venv-live\Scripts\python.exe -m pytest tests/v19/test_phoneonly_runtime.py::test_audio_frame_conversion_reaches_pcm_callback tests/v19/test_phoneonly_runtime.py::test_vad_segment_is_archived_when_asr_unavailable tests/v19/test_e31_conversation.py::test_wiring_final_segment_reaches_core_turn_buffer
```

risks if modified:

- The audio queue must stay bounded and non-blocking (`services/live-pc/gateway.py:553` to `services/live-pc/gateway.py:562`).
- A fallback microphone must never run concurrently with the nominal WebRTC PCM feed.
- Final drain order must remain: stop accepting media -> drain audio -> flush AudioRT -> pipeline end (`services/live-pc/phoneonly_runtime.py:196` to `services/live-pc/phoneonly_runtime.py:210`).

## 04. Live video

status: `partially_proven`

objective: Android rear-camera frames and their `FrameEnvelope` metadata become WebRTC video, aiortc receives frames, `LivePipeline.run_video()` calls VisionRT/WorldBrain, and neutral poses are never spatialised unless `pose_valid` is true.

real entry:

- Unity frame event: `apps/xr-mobile/Assets/Scripts/Transport/LiveTransportBridge.cs:89` subscribes `EyeCaptureSource.OnFrame`.
- PC video track: `services/live-pc/gateway.py:463` `@pc.on("track")`.

call trace:

- `LiveTransportBridge.OnEnable()` subscribes `_capture.OnFrame += HandleFrame` at `apps/xr-mobile/Assets/Scripts/Transport/LiveTransportBridge.cs:89` to `apps/xr-mobile/Assets/Scripts/Transport/LiveTransportBridge.cs:91`.
- `EyeCaptureSource` serialises `FrameEnvelope`, including the additive `pose_valid` field introduced in E60.
- `HandleFrame()` sends the `FrameEnvelope` over DataChannel and pushes texture/video frame to the native feeder at `apps/xr-mobile/Assets/Scripts/Transport/LiveTransportBridge.cs:233` to `apps/xr-mobile/Assets/Scripts/Transport/LiveTransportBridge.cs:239`. Boundary: Unity texture/JNI/DataChannel metadata.
- Kotlin creates video track `cam0` and `pc.addTrack(track, ...)` at `apps/xr-mobile/android/livetransport/src/main/java/com/mlomega/xr/livetransport/LiveTransportPlugin.kt:378` to `apps/xr-mobile/android/livetransport/src/main/java/com/mlomega/xr/livetransport/LiveTransportPlugin.kt:389`.
- PC track handler branches `track.kind == "video"` and schedules `_consume_track(track, pc)` at `services/live-pc/gateway.py:463` to `services/live-pc/gateway.py:466`.
- `_consume_track()` awaits `track.recv()`, converts to `bgr24`, offers decoded frames to the active clip recorder, matches the pending envelope and places the latest frame into the queue at `services/live-pc/gateway.py:483` to `services/live-pc/gateway.py:531`.
- `PhoneOnlyRuntime.start()` launches `self.pipeline.run_video()` at `services/live-pc/phoneonly_runtime.py:119` to `services/live-pc/phoneonly_runtime.py:123`.
- `LivePipeline.run_video()` iterates `async for frame_bgr, envelope in self.ingress` and calls `on_video_frame()` at `services/live-pc/live_pipeline.py:1237` to `services/live-pc/live_pipeline.py:1242`.
- E60 gates spatialisation on `FrameEnvelope.pose_valid`; a neutral/default pose is retained as non-spatial metadata instead of being treated as a real world pose.
- Vision work that can block is dispatched with `asyncio.to_thread`, keeping the live loop responsive.
- `LivePipeline.on_video_frame()` -> `self.vision.process_frame()` at `services/live-pc/live_pipeline.py:809` and `services/live-pc/live_pipeline.py:833`.
- `VisionRT.process_frame()` records keyframes and emits scene deltas at `services/live-pc/visionrt.py:481` to `services/live-pc/visionrt.py:523`.
- `LivePipeline._on_scene_delta()` sends `scene_delta` over DataChannel and mirrors it into WorldBrain at `services/live-pc/live_pipeline.py:757` to `services/live-pc/live_pipeline.py:766`.
- `WorldBrain.ingest_scene_delta()` persists last-seen/change/world state at `services/live-pc/worldbrain.py:351` to `services/live-pc/worldbrain.py:428`; E60 derives stable entity identifiers without the transport session so identity can survive session boundaries.

tables read/write:

- `vision_frames` / `raw_assets` via `register_xr_keyframe()` from `services/live-pc/visionrt.py:748` and `services/live-pc/visionrt.py:758`.
- `visual_events_v19`, `scene_session_summaries_v19`, world-state tables through WorldBrain store calls.

tests existing:

- `tests/v19/test_transport_webrtc.py:81` WebRTC loop delivers frames with pose.
- `tests/v19/test_transport_webrtc.py:149` SessionHub `/webrtc/offer` delivers frames.
- `tests/v19/test_visionrt.py:69` SceneDelta bound to frame.
- `tests/v19/test_visionrt.py:118` keyframe registered via V19 keyframes.
- `tests/v19/test_e28_worldbrain.py:172` last-seen persisted.
- E60 unit coverage proves `pose_valid` gating and stable cross-session entity IDs; exact test filenames were not preserved in the supplied delta.

tests missing:

- Real Android camera -> Kotlin WebRTC -> aiortc -> `run_video()` hardware proof, including valid/invalid pose transitions.

command:

```powershell
.\.venv-live\Scripts\python.exe -m pytest tests/v19/test_transport_webrtc.py tests/v19/test_visionrt.py tests/v19/test_e28_worldbrain.py
```

risks if modified:

- Do not block the live video loop with clip encoding; the recorder path must remain best-effort.
- DataChannel frame metadata and video-frame matching are asynchronous; changing envelope shape can silently break alignment.
- `pose_valid=false` must never produce a spatial anchor from a neutral/default pose.
- Stable world entity IDs must not include the transport session identifier.

## 05. Wake word / command routing

status: `partially_proven`

objective: Device wake-word state gates command routing while all final speech continues into memory; the configured wake word can also be changed at runtime with an acknowledged PC↔device command.

real entry:

- Device ASR final: `AsrKwsService.decodeSegment()` in `apps/xr-mobile/android/reflexvision/.../AsrKwsService.kt`.
- Unity ASR callback: `apps/xr-mobile/Assets/Scripts/Reflex/AsrBridge.cs:231`.
- PC wake-word push: `LivePipeline.push_wake_word()`.
- PC DataChannel receipt/control callback: `services/live-pc/phoneonly_runtime.py:152`.

call trace:

- Shared PCM reaches `AsrKwsService`; the existing English KWS path remains available.
- E58 adds the production French-final path: `AsrKwsService.decodeSegment()` -> `WakeWordMatcher.matches(finalText)` -> `openCommandWindow()` + `onWakeWord()`.
- `AsrBridge.OnNativeTranscript()` forwards final segments with `isCommand` via `_transport.SendTranscriptSegment(...)` at `apps/xr-mobile/Assets/Scripts/Reflex/AsrBridge.cs:231` to `apps/xr-mobile/Assets/Scripts/Reflex/AsrBridge.cs:238`.
- `LiveTransportBridge.SendTranscriptSegment()` emits `{type:"device_transcript", text, language, start_ms, end_ms, is_final:true, is_command}` at `apps/xr-mobile/Assets/Scripts/Transport/LiveTransportBridge.cs:211` to `apps/xr-mobile/Assets/Scripts/Transport/LiveTransportBridge.cs:224`.
- PC gateway sends non-envelope DataChannel payloads to `PhoneOnlyRuntime._on_receipt()` at `services/live-pc/gateway.py:439` to `services/live-pc/gateway.py:459`.
- Wake/control messages call `LivePipeline.arm_command_window()`; final routing is gated by `_should_route_intent()`, while `ConversationBridge.ingest_segment()` still records background speech.
- Runtime configuration source is `configs/user_profile.yaml` key `wake_word` (default reported by E58: `viki`).
- PC->device update path: `PhoneOnlyRuntime` DataChannel -> `LivePipeline.push_wake_word()` -> `_push_device_command({action:"set_wake_word", word, command_id})`.
- Unity path: `DeviceCommandHandler.Execute()` -> `SetWakeWordRequested` -> `AsrBridge.SetWakeWord()` -> JNI `setWakeWord` on the Kotlin service.
- Device->PC acknowledgement: `{type:"device_command_result", command_id, action, ok}`. The PC retains/retries an unacknowledged wake-word command.

tables read/write:

- Writes BrainLive turns through `ConversationBridge.ingest_segment()` even when command routing is suppressed.
- May enqueue UI deliveries through the intent router depending on the recognised command.

tests existing:

- `tests/v19/test_wake_word_gating.py:82` open policy routes and remembers.
- `tests/v19/test_wake_word_gating.py:94` gated policy routes commands but remembers all speech.
- `tests/v19/test_wake_word_gating.py:143` runtime control message arms the command window.
- `WakeWordMatcherTest.kt` covers device final-text matching.
- E58/E60 unit coverage covers `set_wake_word`, `device_command_result` and retry semantics; exact filenames were not preserved in the supplied delta.

tests missing:

- Real Android ASR final -> `WakeWordMatcher` -> Unity/PC command window over a real DataChannel.
- Runtime wake-word change applied and acknowledged on a physical device.

command:

```powershell
.\.venv-live\Scripts\python.exe -m pytest tests/v19/test_wake_word_gating.py tests/v19/test_e33_intents.py
```

risks if modified:

- Never cut continuous memory ingestion when command routing is gated.
- Do not treat `device_transcript`, `scene_delta`, `tts_audio` or `device_command_result` as `UIIntent`.
- The configured word must remain normalised consistently on PC, Unity and Kotlin.
- Retry must be keyed by `command_id` so duplicate acknowledgements stay idempotent.

## 06. UIIntent delivery

status: `partially_proven`

objective: BrainLive/PC queued UIIntents reach the phone DataChannel, then Unity renders through the phone UI pipeline.

real entry:

- PC queued delivery loop: `services/live-pc/phoneonly_runtime.py:127`.
- Direct live pipeline push: `services/live-pc/live_pipeline.py:626`.

call trace:

- `PhoneOnlyRuntime.start()` launches `_delivery_loop()` at `services/live-pc/phoneonly_runtime.py:123` to `services/live-pc/phoneonly_runtime.py:124`.
- `_delivery_loop()` -> `_dispatch_deliveries()` at `services/live-pc/phoneonly_runtime.py:127` to `services/live-pc/phoneonly_runtime.py:130`.
- `_dispatch_deliveries()` -> `DeliveryAdapter.dispatch_once()` at `services/live-pc/phoneonly_runtime.py:148` to `services/live-pc/phoneonly_runtime.py:150`.
- `DeliveryAdapter.dispatch_once()` -> `poll_queued()` -> SQL `SELECT * FROM brainlive_intervention_delivery_queue WHERE delivery_status='queued'` at `services/live-pc/delivery_adapter.py:87` to `services/live-pc/delivery_adapter.py:91`.
- `DeliveryAdapter.dispatch_once()` maps row to UIIntent and `await self.renderer.push(intent)` at `services/live-pc/delivery_adapter.py:94` to `services/live-pc/delivery_adapter.py:99`.
- `DataChannelRenderer.push()` -> `ingress.send_ui_intent(payload)` at `services/live-pc/phoneonly_runtime.py:32` to `services/live-pc/phoneonly_runtime.py:43`.
- `AiortcIngress.send_ui_intent()` marshals to owner loop or calls `_send_ui_intent_now()` at `services/live-pc/gateway.py:324` to `services/live-pc/gateway.py:347`. Boundary: `datachannel_boundary`.
- Unity `LiveTransportBridge.OnNativeMessage()` deserializes UIIntent and raises `UiIntentReceived` at `apps/xr-mobile/Assets/Scripts/Transport/LiveTransportBridge.cs:369` to `apps/xr-mobile/Assets/Scripts/Transport/LiveTransportBridge.cs:383`.
- `TransportIntentSource.OnEnable()` subscribes bridge event and `Forward()` raises `IntentProduced` at `apps/xr-mobile/Assets/Scripts/UI/TransportIntentSource.cs:26` to `apps/xr-mobile/Assets/Scripts/UI/TransportIntentSource.cs:36`.
- `UIIntentBroker.RegisterSource()` subscribes source events at `apps/xr-mobile/Assets/Scripts/UI/UIIntentBroker.cs:185` to `apps/xr-mobile/Assets/Scripts/UI/UIIntentBroker.cs:189`.
- `UIRuntime.Awake()` subscribes `IntentAdmitted`, and `OnAdmitted()` renders components at `apps/xr-mobile/Assets/Scripts/UI/UIRuntime.cs:50` to `apps/xr-mobile/Assets/Scripts/UI/UIRuntime.cs:71` and `apps/xr-mobile/Assets/Scripts/UI/UIRuntime.cs:88` to `apps/xr-mobile/Assets/Scripts/UI/UIRuntime.cs:110`.
- E53 registers `task_panel` and `task_anchor` in `UIComponentRegistry`; `TaskPanelComponent` and `TaskAnchorComponent` use the 12-atom `UI/Components/TaskAtoms/` bank and follow `SceneCache.Tracks` for grounded anchors.

tables read/write:

- Reads `brainlive_intervention_delivery_queue`.
- Writes feedback `delivered` through `record_delivery_feedback()` at `services/live-pc/delivery_adapter.py:99`.

tests existing:

- `tests/v19/test_phoneonly_runtime.py:368` BrainLive delivery queue reaches phone DataChannel.
- `tests/v19/test_delivery_adapter.py:14` delivery row maps to UIIntent.
- `apps/xr-mobile/Assets/Tests/EditMode/UIComponentRegistryTests.cs:12` component mapping, including E53 task components.
- E53 EditMode suite reports nine task-atom/registry tests.
- `tests/v19/test_phoneonly_android_wiring.py:43` PhoneOnly scene includes UI path components.

tests missing:

- Real Android DataChannel UIIntent -> visible phone UI component, including `task_panel` and grounded `task_anchor`.

command:

```powershell
.\.venv-live\Scripts\python.exe -m pytest tests/v19/test_phoneonly_runtime.py::test_brainlive_delivery_queue_reaches_phone_datachannel tests/v19/test_delivery_adapter.py
```

risks if modified:

- If UIIntent component names diverge from Unity registry, PC will deliver JSON but phone renders nothing.
- The delivery loop treats DataChannel absence as `ConnectionError`; it must not end the session on reconnect gaps.

## 06A. Help mode

status: `partially_proven`

objective: A spoken help request becomes a persisted micro-action plan, a task panel and a grounded next-step anchor, with active-session controls and recovery.

real entry:

- `IntentRouter.on_transcript()` pre-routes `help_start` and active controls such as “c’est fait” and “répète”.
- `services/live-pc/help_mode.py` `HelpTaskEngine`.

call trace:

- `IntentRouter._do_help_start()` -> `HelpTaskEngine.start_from_description()`.
- Start performs at most one `_guess_scene_context()` VLM glance, then calls `llm_router.complete_json()` for a structured micro-action plan.
- `_adopt_plan()` persists/replaces the active plan in `help_mode_tasks` and advances the state machine.
- The engine enqueues `task_panel` through the normal H1/delivery path and emits `task_anchor` on the hot path.
- Grounding resolves tracks by `label_en`; ghost N+1 and watchdog indices keep the next action visible/recoverable.
- Unity maps `task_panel|task_anchor` to `TaskPanelComponent|TaskAnchorComponent`, backed by the 12 TaskAtoms and `SceneCache.Tracks`.

tables read/write:

- Reads/writes `help_mode_tasks` for active-plan persistence and resume.
- Uses the normal delivery tables for queued task panels.

tests existing:

- E53 PC suite reported 62 passing help-mode tests.
- E53 Unity EditMode suite reported nine passing task component tests.

tests missing:

- Physical-device render, anchor tracking and resume after process/device restart.

command:

```powershell
# Exact E53 test file names were not included in the supplied artefacts; refresh from checkout before execution.
rg -n "HelpTaskEngine|help_mode_tasks|task_panel|task_anchor" services/live-pc apps/xr-mobile tests
```

risks if modified:

- Do not call the VLM more than once at help-session start unless the contract is deliberately changed.
- Active controls must be pre-routed before generic intent parsing.
- A task anchor without a matching live track must degrade to panel-only guidance, not fabricate spatial grounding.

## 06B. Reflex activation

status: `partially_proven`

objective: Production PhoneOnly lifecycle signals actually reach `ReflexScheduler`, activating ASR, gestures, translation/subtitles and related local skills.

real entry:

- `apps/xr-mobile/Assets/Scripts/Reflex/PhoneOnlyReflexSignalSource.cs`.

call trace:

- `PhoneOnlyReflexSignalSource` observes production pairing/transport/capture lifecycle.
- It calls `ReflexScheduler.RaiseSignal(...)` for the relevant availability/activity transitions.
- Scheduler decisions activate/deactivate ASR, gesture and translation/subtitle skills.
- Before E60 the scheduler had no production caller in PhoneOnly, so the flow was statically present but dead.

tables read/write: none.

tests existing:

- E60 unit coverage proves the production signal source reaches `ReflexScheduler`.

tests missing:

- Physical-device proof that ASR, gestures and offline subtitles start/stop from real lifecycle transitions.

risks if modified:

- Do not regress to editor/demo-only signal injection.
- Repeated lifecycle signals must stay idempotent and must not open a second microphone.

## 06C. TTS audio delivery

status: `partially_proven`

objective: PC-generated TTS audio reaches a real Unity consumer instead of ending at an unhandled DataChannel message.

real entry:

- `LivePipeline(enable_tts=True)`.
- `apps/xr-mobile/Assets/Scripts/UI/TtsAudioPlayer.cs`.

call trace:

- PhoneOnly runtime constructs `LivePipeline` with TTS enabled.
- Pipeline emits a `tts_audio` DataChannel payload.
- `LiveTransportBridge.OnNativeMessage()` dispatches the typed payload.
- `TtsAudioPlayer` decodes/queues playback on Unity audio output.

tables read/write: none.

tests existing:

- E60 unit wiring coverage reports the PC producer and Unity consumer are connected.

tests missing:

- Real Android playback, interruption, volume/route and reconnect behaviour.

risks if modified:

- `tts_audio` is not a `UIIntent`; keep transport dispatch types separate.
- Playback buffering must not block the Unity main thread or DataChannel receive callback.

## 06D. Panel manipulation

status: `partially_proven`

objective: A pinch over a manipulable panel moves/resizes/closes/minimises that panel; an unclaimed pinch preserves the existing LensWindow zoom fallback.

real entry:

- `GestureBridge` pinch `(x,y)` callback.
- `apps/xr-mobile/Assets/Scripts/Reflex/PanelManipulator.cs`.

call trace:

- `GestureBridge` forwards pinch coordinates to `PanelManipulator`.
- `PanelManipulator` performs claim/hit-test through `ManipulablePanelRegistry`.
- A claimed target invokes `IManipulablePanel.MoveTo`, `Resize`, `Close` or `Minimise`.
- An unclaimed pinch falls through to the unchanged `LensWindowSkill` zoom path.
- This flow is Unity-only and adds no network contract.

tables read/write: none.

tests existing:

- E59 EditMode suite reported 76/76 passing tests.

tests missing:

- Physical-device precision/latency and conflict testing across several overlapping panels.

risks if modified:

- Claim must occur before the LensWindow fallback.
- Hit-test coordinates must use the same screen/canvas space as panel bounds.


## 07. UIReceipt feedback

status: `partially_proven`

objective: Phone UI receipts (`displayed`, `seen`, `acted`, `dismissed`, `corrected`) return to PC and persist into V18.8 feedback.

real entry:

- Unity UI component receipt emit: `apps/xr-mobile/Assets/Scripts/UI/Components/UIComponentBase.cs:299`.
- Transport sink: `apps/xr-mobile/Assets/Scripts/UI/UIReceiptTransportSink.cs:127`.

call trace:

- `UIComponentBase.EmitReceipt()` builds `UIReceipt` and calls `Sink.Send(receipt)` at `apps/xr-mobile/Assets/Scripts/UI/Components/UIComponentBase.cs:299` to `apps/xr-mobile/Assets/Scripts/UI/Components/UIComponentBase.cs:312`.
- `UIReceiptTransportSink.Send()` -> `ReceiptOutbox.Send()` at `apps/xr-mobile/Assets/Scripts/UI/UIReceiptTransportSink.cs:127` to `apps/xr-mobile/Assets/Scripts/UI/UIReceiptTransportSink.cs:130`.
- `TrySendOverBridge()` checks connected transport and calls `_bridge.SendReceipt(receipt)` at `apps/xr-mobile/Assets/Scripts/UI/UIReceiptTransportSink.cs:145` to `apps/xr-mobile/Assets/Scripts/UI/UIReceiptTransportSink.cs:149`.
- `LiveTransportBridge.SendReceipt()` serializes and calls Kotlin `sendContractMessage` at `apps/xr-mobile/Assets/Scripts/Transport/LiveTransportBridge.cs:160` to `apps/xr-mobile/Assets/Scripts/Transport/LiveTransportBridge.cs:164`. Boundary: `jni_boundary`.
- Kotlin `LiveTransportPlugin.sendContractMessage()` sends DataChannel buffer at `apps/xr-mobile/android/livetransport/src/main/java/com/mlomega/xr/livetransport/LiveTransportPlugin.kt:130` to `apps/xr-mobile/android/livetransport/src/main/java/com/mlomega/xr/livetransport/LiveTransportPlugin.kt:135`.
- PC `@channel.on("message")` treats non-envelope as receipt and calls `self.on_receipt(...)` at `services/live-pc/gateway.py:439` to `services/live-pc/gateway.py:459`.
- `PhoneOnlyRuntime._on_receipt()` parses `UIReceipt` and calls `delivery_adapter.record_receipt(receipt)` at `services/live-pc/phoneonly_runtime.py:178` to `services/live-pc/phoneonly_runtime.py:180`.
- `DeliveryAdapter.record_receipt()` -> `record_delivery_feedback()` at `services/live-pc/delivery_adapter.py:103` to `services/live-pc/delivery_adapter.py:108`.

tables read/write:

- Writes `brainlive_intervention_feedback_events_v188` via `mlomega_audio_elite.v18_8_live_policy.record_delivery_feedback()` (`src/mlomega_audio_elite/v18_8_live_policy.py:757`).

tests existing:

- `tests/v19/test_e24_roundtrip.py:61` frame -> UIIntent -> UIReceipt -> feedback table.
- `apps/xr-mobile/Assets/Tests/EditMode/UIReceiptLifecycleTests.cs:18`.
- `apps/xr-mobile/Assets/Tests/EditMode/UIReceiptOutboxTests.cs:14`.

tests missing:

- Real Android UI action receipt over Kotlin WebRTC DataChannel to PC.

command:

```powershell
.\.venv-live\Scripts\python.exe -m pytest tests/v19/test_e24_roundtrip.py
```

risks if modified:

- Receipt must carry `delivery_id`; `DeliveryAdapter.record_receipt()` intentionally returns `None` without it at `services/live-pc/delivery_adapter.py:103` to `services/live-pc/delivery_adapter.py:105`.

## 08. Explicit end session

status: `partially_proven`

objective: Only explicit authenticated user action ends the PhoneOnly runtime; WebRTC disconnect alone must not end/CloseDay.

real entry:

- Unity user action: `apps/xr-mobile/Assets/Scripts/Transport/PhoneOnlySessionCoordinator.cs:156`.
- PC route: `services/live-pc/sessionhub_http.py:404` `POST /session/end`.

call trace:

- UI button calls `EndSessionAndCloseDay()` at `apps/xr-mobile/Assets/Scripts/Transport/PhoneOnlySessionCoordinator.cs:153` to `apps/xr-mobile/Assets/Scripts/Transport/PhoneOnlySessionCoordinator.cs:157`.
- `EndSessionAndCloseDay()` obtains session/token and starts `EndExplicitly(sid, token)` at `apps/xr-mobile/Assets/Scripts/Transport/PhoneOnlySessionCoordinator.cs:77` to `apps/xr-mobile/Assets/Scripts/Transport/PhoneOnlySessionCoordinator.cs:82`.
- `EndExplicitly()` sends authenticated `POST /session/end` via UnityWebRequest at `apps/xr-mobile/Assets/Scripts/Transport/PhoneOnlySessionCoordinator.cs:85` to `apps/xr-mobile/Assets/Scripts/Transport/PhoneOnlySessionCoordinator.cs:104`. Payload: `session_id`, `token`.
- PC `POST /session/end` parses and authenticates at `services/live-pc/sessionhub_http.py:404` to `services/live-pc/sessionhub_http.py:411`.
- Route resolves runtime and calls `await runtime.end_session_only()` at `services/live-pc/sessionhub_http.py:412` to `services/live-pc/sessionhub_http.py:418`.
- `PhoneOnlyRuntime.end_session_only()` order: `stop_accepting_media()` -> `drain_audio()` -> `pipeline.flush_audio()` -> `close_transport()` -> `pipeline.end_session(strict=True)` -> `conversation.end_session(strict=True)` -> require `live_session_id` -> release caches at `services/live-pc/phoneonly_runtime.py:196` to `services/live-pc/phoneonly_runtime.py:223`.
- Route starts CloseDay task after successful end via `manager.start_close_day(session_id)` at `services/live-pc/sessionhub_http.py:419` to `services/live-pc/sessionhub_http.py:421`.
- WebRTC disconnect path does not call end: `AiortcIngress._consume_track()` explicitly treats track ending as temporary and tears down only the peer at `services/live-pc/gateway.py:535` to `services/live-pc/gateway.py:537`.

tables read/write:

- End flush writes WorldBrain summary through `LivePipeline.end_session()` and `WorldBrain.end_session()`.
- Ends BrainLive session through `ConversationBridge.end_session()` -> `end_live_session()` at `services/live-pc/conversation_bridge.py:268` to `services/live-pc/conversation_bridge.py:274`.

tests existing:

- `tests/v19/test_phoneonly_runtime.py:98` runtime starts pipeline/audio and explicit CloseDay once.
- `tests/v19/test_phoneonly_runtime.py:175` offer creates runtime and end is authenticated.
- `tests/v19/test_phoneonly_runtime.py:206` disconnect teardown does not end or CloseDay.
- `tests/v19/test_phoneonly_runtime.py:315` explicit end waits inflight audio before flush.

tests missing:

- Real Android explicit button press -> `POST /session/end` -> polling completion.

command:

```powershell
.\.venv-live\Scripts\python.exe -m pytest tests/v19/test_phoneonly_runtime.py::test_runtime_starts_pipeline_audio_and_explicit_close_day_once tests/v19/test_phoneonly_runtime.py::test_disconnect_teardown_does_not_end_or_close_day tests/v19/test_phoneonly_runtime.py::test_explicit_end_waits_inflight_audio_before_flush_and_pipeline_end
```

risks if modified:

- Do not call CloseDay from `OnDisable`, `OnDestroy`, WebRTC `disconnected`, or track end.
- Drain order is the sensitive invariant; moving `pipeline.end_session()` before audio drain risks losing the final segment.

## 09. CloseDay

status: `partially_proven`

objective: After explicit end, run CloseDay with the real `person_id` and BrainLive `live_session_id`, idempotently across multiple same-day sessions and recoverably if the normal trigger is missed.

real entry:

- PC `POST /session/end` starts CloseDay after explicit end: `services/live-pc/sessionhub_http.py:421`.
- PC `POST /session/close-day` retries/starts explicitly: `services/live-pc/sessionhub_http.py:424`.
- E60 fallback watchdog in `phoneonly_runtime` checks ended sessions that still lack a completed durable run.

call trace:

- `/session/end` calls `manager.start_close_day(session_id)` after `end_session_only()` completion at `services/live-pc/sessionhub_http.py:418` to `services/live-pc/sessionhub_http.py:421`.
- `/session/close-day` authenticates, requires `runtime.ended`, then calls `manager.start_close_day(session_id)` at `services/live-pc/sessionhub_http.py:424` to `services/live-pc/sessionhub_http.py:438`.
- `end_session_only()` captures `ConversationBridge.live_session_id` and rejects a missing durable ID at `services/live-pc/phoneonly_runtime.py:211` to `services/live-pc/phoneonly_runtime.py:218`.
- E60 `_completed_close_day_exists()` queries the durable DB instead of trusting an in-memory completed counter, preserving correct same-day multi-session/rerun semantics.
- `SinglePhoneRuntimeManager.start_close_day()` reuses an active task, returns durable completion when present, or schedules `runtime.run_close_day()`.
- The watchdog provides a secondary start path only after explicit end; disconnect, `OnDisable`, track end and process loss are still not semantic session ends.
- `_run_close_day()` shells to `scripts/run_phoneonly_close_day.py --person-id ... --live-session-id ...` using the core `.venv`.
- Worker calls `close_brainlive_day(person_id=..., live_session_id=...)`.
- Core CloseDay keeps durable checkpoints, post-stop deep audio/vision, longitudinal, Life Model, prediction and self-schema stages.
- E60 visual consolidation uses `Europe/Paris` day boundaries and the CloseDay manifest re-reads the actual persisted tables before finalising counts/status.

tables read/write:

- Reads/writes `v18_close_day_runs` and `v18_pipeline_stages` plus core BrainLive, visual, vector and Life Model tables.
- Completion lookup is DB-backed, not process-memory-backed.

tests existing:

- `tests/v19/test_phoneonly_runtime.py:98` CloseDay once/idempotence at runtime level.
- `tests/v19/test_multi_session_close_day.py:245` manager allow-rerun semantics.
- `tests/v19/test_multi_session_close_day.py:265` subprocess command carries allow-rerun.
- `tests/v19/test_ollama_context_budget.py:28` truncated JSON is never applied.
- E60 unit coverage covers DB completion lookup, watchdog, manifest refresh and Paris day boundary; exact filenames were not preserved in the supplied delta.

tests missing:

- Full heavy CloseDay worker over a real Android PhoneOnly session and real production data/models.

command:

```powershell
.\.venv-live\Scripts\python.exe -m pytest tests/v19/test_phoneonly_runtime.py tests/v19/test_multi_session_close_day.py tests/v19/test_ollama_context_budget.py
```

risks if modified:

- Passing transport `session_id` instead of `ConversationBridge.live_session_id` breaks consolidation.
- A disconnect must never become an implicit end.
- Same-day completion must be decided from durable run identity, not a global/in-memory “already ran today” flag.
- Day bucketing must stay explicit (`Europe/Paris`) and manifests must reflect final persisted tables.

## 10. Visual evidence / clips

status: `partially_proven`

objective: Store keyframes/proofs and optional clips without blocking live video; ensure the recorder and GPU arbiter are actually constructed in the production runtime, while referenced proof media remains reachable.

real entry:

- PhoneOnly runtime composition constructs `ClipRecorder` and `GpuArbiter`.
- Vision keyframe: `services/live-pc/visionrt.py:517`.
- Clip recorder offer: `services/live-pc/gateway.py:514`.

call trace:

- E60 `phoneonly_runtime` constructs and starts `ClipRecorder`, passes it through `ingress_kwargs["clip_recorder"]`, and constructs `GpuArbiter` via the runtime arbiter factory.
- `AiortcIngress._consume_track()` offers decoded BGR frames to the active recorder at `services/live-pc/gateway.py:514` to `services/live-pc/gateway.py:518`. Boundary: best-effort, non-blocking.
- `ClipRecorder.start()` runs a daemon pump thread at `services/live-pc/clip_recorder.py:374` to `services/live-pc/clip_recorder.py:381`.
- `ClipRecorder._run()` encodes frames and closes segments at `services/live-pc/clip_recorder.py:396` to `services/live-pc/clip_recorder.py:420`.
- `VisionRT.process_frame()` calls `_record_keyframe()` when the selector fires at `services/live-pc/visionrt.py:516` to `services/live-pc/visionrt.py:518`.
- `default_keyframe_sink()` writes JPEG into managed media storage and calls `register_xr_keyframe()` at `services/live-pc/visionrt.py:731` to `services/live-pc/visionrt.py:765`.
- `WorldBrain.ingest_scene_delta()` creates frame evidence references.
- Retention/tiering keeps referenced media and only purges unreferenced assets under policy.

tables read/write:

- Keyframes: `raw_assets`, `vision_frames`.
- World evidence: `visual_events_v19`, `scene_session_summaries_v19`, world entity/link tables.
- Clips: `visual_evidence_assets_v19` plus retention reads.

tests existing:

- `tests/v19/test_visionrt.py:118` keyframe recorded via V19 keyframes.
- `tests/v19/test_clip_recorder.py:124` segment written/indexed/replay finds it.
- `tests/v19/test_media_retention.py:93` referenced keyframe never selected for purge.
- E60 unit composition coverage resolves the former dead-wiring mismatch for `ClipRecorder` and `GpuArbiter`.

tests missing:

- Real live clip capture and replay from Android WebRTC video.
- Physical-device matrix proving nominal arbiter/recorder behaviour under GPU pressure.

command:

```powershell
.\.venv-live\Scripts\python.exe -m pytest tests/v19/test_visionrt.py::test_keyframe_recorded_via_v19_keyframes tests/v19/test_clip_recorder.py tests/v19/test_media_retention.py
```

risks if modified:

- Keyframes must not land in temporary folders.
- Clip encoding must remain best-effort and never block `_consume_track()`.
- Runtime composition tests must fail if recorder/arbiter construction is removed again.
- “Constructed” is not hardware validation; the S25/device path remains `to_verify`.

## 11. Model provisioning

status: `partially_proven`

objective: After pairing, Android downloads missing device-local models from PC with authenticated endpoints and sha256 verification.

real entry:

- Unity `ModelProvisioningBridge.TryStart()` at `apps/xr-mobile/Assets/Scripts/Core/ModelProvisioningBridge.cs:126`.

call trace:

- `ModelProvisioningBridge.TryStart()` waits for installer and active session/token at `apps/xr-mobile/Assets/Scripts/Core/ModelProvisioningBridge.cs:126` to `apps/xr-mobile/Assets/Scripts/Core/ModelProvisioningBridge.cs:136`.
- Android-only `StartAndroid(baseUrl, sessionId, token)` at `apps/xr-mobile/Assets/Scripts/Core/ModelProvisioningBridge.cs:139` to `apps/xr-mobile/Assets/Scripts/Core/ModelProvisioningBridge.cs:148`.
- Unity constructs Kotlin `ModelProvisioner` and calls `start(baseUrl, sessionId, token)` at `apps/xr-mobile/Assets/Scripts/Core/ModelProvisioningBridge.cs:156` to `apps/xr-mobile/Assets/Scripts/Core/ModelProvisioningBridge.cs:160`. Boundary: `jni_boundary`.
- Kotlin `ModelProvisioner.provision()` fetches manifest, parses it, computes missing entries, downloads each missing model at `apps/xr-mobile/android/livetransport/src/main/java/com/mlomega/xr/livetransport/ModelProvisioner.kt:99` to `apps/xr-mobile/android/livetransport/src/main/java/com/mlomega/xr/livetransport/ModelProvisioner.kt:110`.
- Kotlin `fetchManifest()` GETs `{base}/models/device/manifest?session_id=...&token=...` at `apps/xr-mobile/android/livetransport/src/main/java/com/mlomega/xr/livetransport/ModelProvisioner.kt:188` to `apps/xr-mobile/android/livetransport/src/main/java/com/mlomega/xr/livetransport/ModelProvisioner.kt:194`.
- Kotlin `downloadOne()` GETs `{base}{entry.endpoint}?session_id=...&token=...`, streams bytes, checks `X-Model-Sha256`, then `installVerified()` at `apps/xr-mobile/android/livetransport/src/main/java/com/mlomega/xr/livetransport/ModelProvisioner.kt:133` to `apps/xr-mobile/android/livetransport/src/main/java/com/mlomega/xr/livetransport/ModelProvisioner.kt:158`.
- PC manifest route `/models/device/manifest` starts at `services/live-pc/sessionhub_http.py:257` and authenticates query through `_authenticate_query()` at `services/live-pc/sessionhub_http.py:251` to `services/live-pc/sessionhub_http.py:255`.
- PC download route `/models/device/{name}` starts at `services/live-pc/sessionhub_http.py:268`.

tables read/write: none; model files under device private/external app model dir, PC serves git-ignored `models/device`.

tests existing:

- `tests/v19/test_device_provisioning.py:100` manifest lists device models.
- `tests/v19/test_device_provisioning.py:132` download streams exact bytes with sha.
- `apps/xr-mobile/android/livetransport/src/test/java/com/mlomega/xr/livetransport/ModelProvisionerCoreTest.kt:35` copy/hash/install primitives.
- `apps/xr-mobile/android/livetransport/src/test/java/com/mlomega/xr/livetransport/DeviceModelManifestTest.kt:14`.

tests missing:

- Actual Android first-launch provisioning from PC over LAN/Tailscale.

command:

```powershell
.\.venv-live\Scripts\python.exe -m pytest tests/v19/test_device_provisioning.py
```

risks if modified:

- Query token auth must stay required for both manifest and binary routes.
- Model provisioning failures intentionally degrade feature availability without crashing the session.

## 12. Memory query

status: `partially_proven`

objective: User asks a memory question, IntentRouter calls MemoryQuery, and a ContextCard UIIntent is emitted.

real entry:

- Audio final transcript reaches `IntentRouter.on_transcript()` via `LivePipeline._handle_audio_intents()` at `services/live-pc/live_pipeline.py:1146` to `services/live-pc/live_pipeline.py:1148`.

call trace:

- `LivePipeline._handle_audio_intents()` calls `self.intents.on_transcript(text)` when wake gate allows at `services/live-pc/live_pipeline.py:1141` to `services/live-pc/live_pipeline.py:1148`.
- IntentRouter grammar includes `ask_memory` patterns at `services/live-pc/intent_router.py:112` to `services/live-pc/intent_router.py:114`.
- `IntentRouter.on_transcript()` entry is `services/live-pc/intent_router.py:311`.
- LLM/grammar normalization sends `ask_memory` to `_do_ask_memory()` at `services/live-pc/intent_router.py:498` to `services/live-pc/intent_router.py:499`.
- `_do_ask_memory()` calls injected `ask_memory(question)` and returns `RoutedIntent(... ui_intent=intent ...)` at `services/live-pc/intent_router.py:591` to `services/live-pc/intent_router.py:601`.
- `MemoryQuery.ask()` calls `_ask_brain2(question)` then falls back to retrieval-only if needed at `services/live-pc/memory_query.py:89` to `services/live-pc/memory_query.py:120`.
- UIIntent delivery then uses flow 06 DataChannel path.

tables read/write:

- Reads Brain2/vector/memory tables through `MemoryQuery._ask_brain2()` or retrieval fallback. The exact table set is indirect; mark specific table edges `to_verify` unless tracing `memory_query.py` internals for a specific query.

tests existing:

- `tests/v19/test_e33_intents.py:167` ask_memory calls Brain2.
- `tests/v19/test_e33_intents.py:194` degraded without LLM.

tests missing:

- Real voice question -> AudioRT final -> IntentRouter -> MemoryQuery -> phone ContextCard.

command:

```powershell
.\.venv-live\Scripts\python.exe -m pytest tests/v19/test_e33_intents.py::test_ask_memory_calls_ask_brain2 tests/v19/test_e33_intents.py::test_ask_memory_degraded_without_llm
```

risks if modified:

- Do not replace MemoryQuery with a direct LLM-only answer; truth/evidence fields in ContextCard are part of the contract.

## 13. Contracts Python ↔ C# ↔ Kotlin

status: `partially_proven`

objective: Shared contracts keep Python validation, generated C# POCOs, Unity JSON, and Kotlin JSON payloads compatible.

real entry:

- Python source of truth: `packages/contracts/python/models.py:14` `FrameEnvelope`, `packages/contracts/python/models.py:39` `UIIntent`, `packages/contracts/python/models.py:45` `UIReceipt`.
- C# generated copies: `apps/xr-mobile/Assets/Scripts/Contracts/UIIntent.cs:1`, `apps/xr-mobile/Assets/Scripts/Contracts/UIReceipt.cs:1`, `apps/xr-mobile/Assets/Scripts/Contracts/FrameEnvelope.cs:1`.

call trace:

- Unity serializes `FrameEnvelope` via `ContractJson.Serialize(envelope)` before sending metadata over DataChannel at `apps/xr-mobile/Assets/Scripts/Transport/LiveTransportBridge.cs:237` to `apps/xr-mobile/Assets/Scripts/Transport/LiveTransportBridge.cs:238`.
- PC gateway parses frame metadata through `FrameEnvelope.model_validate(payload)` at `services/live-pc/gateway.py:449` to `services/live-pc/gateway.py:452`.
- PC serializes UIIntent dicts to JSON and sends through `ingress.send_ui_intent(json.dumps(intent))` at `services/live-pc/live_pipeline.py:626` to `services/live-pc/live_pipeline.py:629`.
- Unity `LiveTransportBridge.OnNativeMessage()` deserializes `UIIntent` with `ContractJson.Deserialize<UIIntent>(json)` at `apps/xr-mobile/Assets/Scripts/Transport/LiveTransportBridge.cs:380` to `apps/xr-mobile/Assets/Scripts/Transport/LiveTransportBridge.cs:383`.
- Unity serializes `UIReceipt` with `ContractJson.Serialize(receipt)` at `apps/xr-mobile/Assets/Scripts/Transport/LiveTransportBridge.cs:160` to `apps/xr-mobile/Assets/Scripts/Transport/LiveTransportBridge.cs:164`.
- PC parses receipt with `delivery_adapter.UIReceipt.model_validate_json(raw)` at `services/live-pc/phoneonly_runtime.py:178` to `services/live-pc/phoneonly_runtime.py:180`.
- Kotlin `SignalingClient` uses manual JSON for signaling payload `{sdp,type,session_id,token}` at `apps/xr-mobile/android/livetransport/src/main/java/com/mlomega/xr/livetransport/SignalingClient.kt:93` to `apps/xr-mobile/android/livetransport/src/main/java/com/mlomega/xr/livetransport/SignalingClient.kt:99`.

tables read/write: none directly.

tests existing:

- `tests/v19/test_contracts.py:21` Python contract round trips.
- `tests/v19/test_contracts.py:27` strict validation.
- `tests/v19/test_csharp_generator.py:37` schema-generated C# exists.
- `tests/v19/test_csharp_generator.py:43` generated C# up-to-date.
- `apps/xr-mobile/Assets/Tests/EditMode/ContractSerializationTests.cs:14`.
- `tests/v19/test_phoneonly_android_wiring.py:59` scene messages are not misparsed as UIIntent.

tests missing:

- Kotlin DataChannel payload compatibility test against Python/C# schemas for all non-schema device messages.

command:

```powershell
.\.venv-live\Scripts\python.exe -m pytest tests/v19/test_contracts.py tests/v19/test_csharp_generator.py tests/v19/test_phoneonly_android_wiring.py
```

risks if modified:

- `device_command`, `scene_delta`, and `device_transcript` are shape-routed live messages, not all generated schemas. They need explicit tests before schema refactors.

## 14. SessionHub auth/token renew

status: `proven`

objective: Session tokens expire, rotate on renew, old tokens are rejected/retired, authenticated routes enforce token/session match.

real entry:

- `services/live-pc/sessionhub.py:45` `SessionHub.create_session()`.
- `services/live-pc/sessionhub_http.py:311` `POST /session/renew`.

call trace:

- `SessionHub.create_session()` purges expired state then writes `_sessions` and `_tokens` at `services/live-pc/sessionhub.py:45` to `services/live-pc/sessionhub.py:61`.
- Token expiry is stamped in `token_expires_at_utc` and `_token_expires_monotonic` at `services/live-pc/sessionhub.py:57` to `services/live-pc/sessionhub.py:58`.
- `SessionHub.renew_token()` checks active or grace-expired token at `services/live-pc/sessionhub.py:89` to `services/live-pc/sessionhub.py:98`.
- `_rotate_token_locked()` removes old token and writes new token at `services/live-pc/sessionhub.py:80` to `services/live-pc/sessionhub.py:86`.
- `_purge_expired_locked()` moves expired active tokens to `_expired_tokens` and later drops sessions after renew grace at `services/live-pc/sessionhub.py:104` to `services/live-pc/sessionhub.py:121`.
- HTTP `_authenticate()` rejects invalid token at `services/live-pc/sessionhub_http.py:217` to `services/live-pc/sessionhub_http.py:219`.
- `/webrtc/offer`, `/session/end`, `/session/close-day`, `/session/status` all call `_authenticate()` before runtime access at `services/live-pc/sessionhub_http.py:385`, `services/live-pc/sessionhub_http.py:411`, `services/live-pc/sessionhub_http.py:431`, and `services/live-pc/sessionhub_http.py:448`.

tables read/write: memory only.

tests existing:

- `tests/v19/test_sessionhub_http.py:176` renew rotates token and revokes old.
- `tests/v19/test_sessionhub_http.py:198` renew requires valid token.
- `tests/v19/test_sessionhub_http.py:207` expired token/session purged.
- `tests/v19/test_phoneonly_runtime.py:175` authenticated `/session/end`.

tests missing:

- Long-running Android renew/resume over real network.

command:

```powershell
.\.venv-live\Scripts\python.exe -m pytest tests/v19/test_sessionhub_http.py::test_renew_rotates_token_and_revokes_old tests/v19/test_sessionhub_http.py::test_expired_token_and_session_are_purged tests/v19/test_phoneonly_runtime.py::test_offer_creates_runtime_and_end_is_authenticated
```

risks if modified:

- Token TTL and renew grace are process-local by design; if persistence is added, session replay and logout semantics need new tests.

## 15. DataChannel delivery

status: `partially_proven`

objective: Reliable ordered `contracts` DataChannel carries frame metadata/control up and UIIntent/device_command/scene_delta down.

real entry:

- Kotlin creates DataChannel: `apps/xr-mobile/android/livetransport/src/main/java/com/mlomega/xr/livetransport/LiveTransportPlugin.kt:303`.
- PC receives DataChannel: `services/live-pc/gateway.py:419`.

call trace:

- Kotlin `LiveTransportPlugin` creates `pc.createDataChannel(config.dataChannelLabel, dcInit)` with ordered=true at `apps/xr-mobile/android/livetransport/src/main/java/com/mlomega/xr/livetransport/LiveTransportPlugin.kt:303` to `apps/xr-mobile/android/livetransport/src/main/java/com/mlomega/xr/livetransport/LiveTransportPlugin.kt:307`.
- PC `@pc.on("datachannel")` stores channel and wires `open`, `close`, `message` handlers at `services/live-pc/gateway.py:419` to `services/live-pc/gateway.py:439`.
- Incoming frame metadata is routed to `self.matcher.add(FrameEnvelope.model_validate(payload))` at `services/live-pc/gateway.py:449` to `services/live-pc/gateway.py:452`.
- Incoming receipt/control is routed to `self.on_receipt(...)` at `services/live-pc/gateway.py:455` to `services/live-pc/gateway.py:459`.
- PC downlink sends via `channel.send(intent_json)` at `services/live-pc/gateway.py:342` to `services/live-pc/gateway.py:347`.
- PC `LivePipeline._push_intent()` downlinks UIIntent at `services/live-pc/live_pipeline.py:626` to `services/live-pc/live_pipeline.py:629`.
- PC `LivePipeline._push_device_command()` downlinks device command at `services/live-pc/live_pipeline.py:633` to `services/live-pc/live_pipeline.py:642`.
- PC `LivePipeline._on_scene_delta()` downlinks scene_delta at `services/live-pc/live_pipeline.py:757` to `services/live-pc/live_pipeline.py:761`.
- Unity raw message routing: `DeviceCommandHandler` subscribes `MessageReceived` and parses device commands at `apps/xr-mobile/Assets/Scripts/UI/DeviceCommandHandler.cs:88` to `apps/xr-mobile/Assets/Scripts/UI/DeviceCommandHandler.cs:109`; `SceneDeltaTransportHandler` subscribes and filters `"scene_delta"` at `apps/xr-mobile/Assets/Scripts/UI/SceneDeltaTransportHandler.cs:24` to `apps/xr-mobile/Assets/Scripts/UI/SceneDeltaTransportHandler.cs:38`; `LiveTransportBridge.OnNativeMessage()` only treats messages with `"ui_intent_id"` as UIIntent at `apps/xr-mobile/Assets/Scripts/Transport/LiveTransportBridge.cs:369` to `apps/xr-mobile/Assets/Scripts/Transport/LiveTransportBridge.cs:383`.

tables read/write:

- Frame metadata itself is in memory; receipts write feedback; UIIntent delivery writes feedback delivered.

tests existing:

- `tests/v19/test_phoneonly_runtime.py:258` DataChannel send from audio worker marshaled to owner loop.
- `tests/v19/test_e24_roundtrip.py:61` UIIntent/UIReceipt over aiortc DataChannel.
- `tests/v19/test_phoneonly_android_wiring.py:59` raw scene messages not misparsed.

tests missing:

- Real Android DataChannel bidirectional path with Kotlin callback to Unity.

command:

```powershell
.\.venv-live\Scripts\python.exe -m pytest tests/v19/test_phoneonly_runtime.py::test_datachannel_send_from_audio_worker_is_marshaled_to_owner_loop tests/v19/test_e24_roundtrip.py tests/v19/test_phoneonly_android_wiring.py::test_raw_scene_messages_are_not_misparsed_as_ui_intents
```

risks if modified:

- Multiple message types share one channel; shape routing must remain explicit to avoid treating control payloads as UIIntent or UIReceipt.

## 16. Media retention / no purge of referenced proof

status: `proven`

objective: CloseDay may transcode/purge unreferenced media but must never delete media referenced by proof/evidence.

real entry:

- Worker after successful CloseDay cleanup gate: `scripts/run_phoneonly_close_day.py:116`.

call trace:

- `run_phoneonly_close_day.py` only runs clip tiering and retention when `cleanup.eligible` is true at `scripts/run_phoneonly_close_day.py:110` to `scripts/run_phoneonly_close_day.py:122`.
- `_run_media_retention()` dynamically loads `services/live-pc/media_retention.py` and calls `run_media_retention(person_id=...)` at `scripts/run_phoneonly_close_day.py:128` to `scripts/run_phoneonly_close_day.py:144`. Boundary: dynamic import.
- `media_retention.py` defines evidence columns scanned for references at `services/live-pc/media_retention.py:57` to `services/live-pc/media_retention.py:70`.
- `MediaRetention._referenced_blob()` / `_is_referenced()` mark media referenced; key lines start at `services/live-pc/media_retention.py:196` and `services/live-pc/media_retention.py:217`.
- `list_media()` flags clips/audio/keyframes referenced before purge at `services/live-pc/media_retention.py:351` to `services/live-pc/media_retention.py:365`.
- `purge_unreferenced()` skips referenced media at `services/live-pc/media_retention.py:526` to `services/live-pc/media_retention.py:538`.
- `enforce_budget()` evicts only unreferenced media and warns if remaining overshoot is all referenced at `services/live-pc/media_retention.py:542` to `services/live-pc/media_retention.py:576`.

tables read/write:

- Reads evidence refs from `visual_events_v19`, `scene_session_summaries_v19`, `world_entity_links_v19`, `brain2_spatial_routine_models`, `life_model_entries_v19`, `predictions_v19`, `prediction_outcomes_v19`, `self_schema_v19`, `brainlive_life_hypotheses`.
- Deletes only unreferenced rows from `vision_frames`, clip/media tables, and audio rows as listed in `services/live-pc/media_retention.py:387` to `services/live-pc/media_retention.py:392`.

tests existing:

- `tests/v19/test_media_retention.py:93` referenced keyframe never selected.
- `tests/v19/test_media_retention.py:111` unreferenced aged purged, referenced kept.
- `tests/v19/test_media_retention.py:150` budget never evicts referenced overshoot.

tests missing:

- End-to-end real CloseDay retention pass over a production-sized media DB.

command:

```powershell
.\.venv-live\Scripts\python.exe -m pytest tests/v19/test_media_retention.py
```

risks if modified:

- Any new evidence table/column must be added to `_EVIDENCE_COLUMNS`, otherwise retention can misclassify proof media as unreferenced.

## 17. Qdrant/vector sync

status: `partially_proven`

objective: Post-stop/CloseDay synchronizes canonical memory rows into the vector backend incrementally.

real entry:

- CloseDay post-stop stage: `src/mlomega_audio_elite/v18_close_day.py:415`.
- Post-stop secondary memory sync: `src/mlomega_audio_elite/brainlive_poststop_deep_flow_v15_15.py:146`.

call trace:

- `close_brainlive_day()` runs `run_brainlive_post_stop_deep_flow(...)` in `do_post_stop()` at `src/mlomega_audio_elite/v18_close_day.py:415` to `src/mlomega_audio_elite/v18_close_day.py:428`.
- `brainlive_poststop_deep_flow._sync_secondary_memory_for_conversation()` imports and calls `sync_vectors(conversation_id=conversation_id, person_id=person_id)` at `src/mlomega_audio_elite/brainlive_poststop_deep_flow_v15_15.py:146` to `src/mlomega_audio_elite/brainlive_poststop_deep_flow_v15_15.py:164`.
- `vector_sync.sync_vectors()` wraps `_sync_vectors_untracked()` in a tracked sync job at `src/mlomega_audio_elite/vector_sync.py:577` to `src/mlomega_audio_elite/vector_sync.py:591`.
- `_sync_vectors_untracked()` gets embedder/vector store, reads memory rows, skips unchanged by `vector_sync_manifest`, embeds text, batches points, and `store.upsert(batch)` at `src/mlomega_audio_elite/vector_sync.py:501` to `src/mlomega_audio_elite/vector_sync.py:563`.
- Manifest writes use `upsert(con, "vector_sync_manifest", ...)` at `src/mlomega_audio_elite/vector_sync.py:523` to `src/mlomega_audio_elite/vector_sync.py:527`.

tables read/write:

- Reads all memory payload sources via `_iter_memory_rows()` (specific tables dynamic inside `vector_sync.py`).
- Writes `vector_sync_manifest`.
- Writes external Qdrant/LanceDB vector collection through `store.upsert(batch)`.

tests existing:

- Direct vector-sync tests not clearly identified in this pass. Existing post-stop/CloseDay tests may mock or skip heavy backend.

tests missing:

- Real Qdrant upsert smoke test with local backend enabled and one post-stop conversation.

command:

```powershell
.\.venv-live\Scripts\python.exe -m pytest tests/v19 -k "vector or sync"
```

risks if modified:

- Full rebuild (`full=True`) should not be used from incremental post-stop path; it would re-embed too much and slow CloseDay.

## 18. Life Model update

status: `proven`

objective: CloseDay updates Life Model V19 incrementally from visual events/prediction outcomes without regenerating or deleting the whole model.

real entry:

- CloseDay Life Model stage: `src/mlomega_audio_elite/v18_close_day.py:497`.

call trace:

- `close_brainlive_day()` imports `run_life_model_v19_stage` and calls it inside GPU phase at `src/mlomega_audio_elite/v18_close_day.py:497` to `src/mlomega_audio_elite/v18_close_day.py:500`.
- `run_life_model_v19_stage()` starts at `src/mlomega_audio_elite/v19_life_model_store.py:180`.
- It ensures schemas at `src/mlomega_audio_elite/v19_life_model_store.py:198` to `src/mlomega_audio_elite/v19_life_model_store.py:201`.
- It reads day `visual_events_v19` at `src/mlomega_audio_elite/v19_life_model_store.py:207` to `src/mlomega_audio_elite/v19_life_model_store.py:213`.
- It reads active `life_model_entries_v19` at `src/mlomega_audio_elite/v19_life_model_store.py:215` to `src/mlomega_audio_elite/v19_life_model_store.py:220`.
- It reads refuted `prediction_outcomes_v19` at `src/mlomega_audio_elite/v19_life_model_store.py:222` to `src/mlomega_audio_elite/v19_life_model_store.py:230`.
- It reads `predictions_v19` at `src/mlomega_audio_elite/v19_life_model_store.py:233` to `src/mlomega_audio_elite/v19_life_model_store.py:237`.
- It applies deltas and returns counts; `life_model_entries_v19` writes are through `apply_life_model_delta()` / `upsert()` at `src/mlomega_audio_elite/v19_life_model_store.py:58` to `src/mlomega_audio_elite/v19_life_model_store.py:65` and updates at `src/mlomega_audio_elite/v19_life_model_store.py:99` to `src/mlomega_audio_elite/v19_life_model_store.py:108`.

tables read/write:

- Reads: `visual_events_v19`, `life_model_entries_v19`, `prediction_outcomes_v19`, `predictions_v19`.
- Writes: `life_model_entries_v19`.

tests existing:

- `tests/v19/test_life_model_v19.py:92` incremental stage confirms/updates.
- `tests/v19/test_life_model_v19.py:145` stale weakening/no delete.
- `tests/v19/test_life_model_empty_day.py` empty-day behavior.

tests missing:

- Full CloseDay Life Model stage with real previous-day production data.

command:

```powershell
.\.venv-live\Scripts\python.exe -m pytest tests/v19/test_life_model_v19.py tests/v19/test_life_model_empty_day.py
```

risks if modified:

- Life Model stage must stay incremental. Regeneration or deletion would contradict `src/mlomega_audio_elite/v19_life_model_store.py:187` to `src/mlomega_audio_elite/v19_life_model_store.py:197`.

## 19. Dashboard read-only

status: `partially_proven`

objective: Memory dashboard reads SQLite without mutating the user memory DB.

real entry:

- `scripts/RUN_DASHBOARD.ps1:31` starts Streamlit app.
- `apps/memory-dashboard/app.py:1699` `main()`.

call trace:

- `RUN_DASHBOARD.ps1` launches `streamlit run apps/memory-dashboard/app.py` at `scripts/RUN_DASHBOARD.ps1:31` to `scripts/RUN_DASHBOARD.ps1:32`.
- Dashboard opens SQLite with `file:{path}?mode=ro` at `apps/memory-dashboard/app.py:476` to `apps/memory-dashboard/app.py:481`. Boundary: `db_boundary`.
- `list_tables_cached()` uses `connect_readonly()` and `SELECT name FROM sqlite_master` at `apps/memory-dashboard/app.py:486` to `apps/memory-dashboard/app.py:490`.
- Multiple cached readers call `connect_readonly()` at `apps/memory-dashboard/app.py:488`, `apps/memory-dashboard/app.py:498`, `apps/memory-dashboard/app.py:508`, `apps/memory-dashboard/app.py:592`, `apps/memory-dashboard/app.py:640`, `apps/memory-dashboard/app.py:1355`, and `apps/memory-dashboard/app.py:1708`.

tables read/write:

- Reads many selected tables depending on UI section.
- No write path proven in dashboard code during this pass; `connect_readonly()` enforces SQLite read-only URI.

tests existing:

- No dedicated dashboard test found in this pass.

tests missing:

- Smoke test that dashboard opens an existing DB in `mode=ro` and rejects writes.

command:

```powershell
rg -n "connect_readonly|mode=ro|INSERT|UPDATE|DELETE" apps/memory-dashboard/app.py scripts/RUN_DASHBOARD.ps1
```

risks if modified:

- Adding any interactive write/repair action in dashboard must use a separate explicit maintenance command, not the read-only connection.

## 20. Installer/onboarding

status: `partially_proven`

objective: Windows launcher/onboarding distinguishes SimOnly, LivePhone/PhoneOnly, Unity build, and dashboard without pretending hardware validation.

real entry:

- `scripts/RUN_MLOMEGA_V19.ps1:12` parameters.
- Unity APK build menu: `apps/xr-mobile/Assets/Scripts/Editor/AndroidBuild.cs:53`.
- Welcome/onboarding script: `scripts/WELCOME_MLOMEGA.ps1`.

call trace:

- `RUN_MLOMEGA_V19.ps1` defines `-SimOnly` and `[Alias("PhoneOnly")] -LivePhone` at `scripts/RUN_MLOMEGA_V19.ps1:12` to `scripts/RUN_MLOMEGA_V19.ps1:18`.
- `-LivePhone` preflights live dependencies and prints Android address, `/health`, `/metrics` at `scripts/RUN_MLOMEGA_V19.ps1:54` to `scripts/RUN_MLOMEGA_V19.ps1:69`.
- `-LivePhone` launches PC runtime `services/live-pc/sessionhub_http.py --host --port --person-id` at `scripts/RUN_MLOMEGA_V19.ps1:70`.
- `-SimOnly` path remains separate below `scripts/RUN_MLOMEGA_V19.ps1:74`; it runs `scripts/simonly_demo_v19.py` and does not start PhoneOnly runtime.
- PhoneOnly scene builder creates real session, pairing, capture, transport, model provisioning, coordinator, UI path, ASR, gestures at `apps/xr-mobile/Assets/Scripts/Editor/PhoneOnlySceneBuilder.cs:38` to `apps/xr-mobile/Assets/Scripts/Editor/PhoneOnlySceneBuilder.cs:80`.
- Android build invokes PhoneOnly scene build before APK validation at `apps/xr-mobile/Assets/Scripts/Editor/AndroidBuild.cs:156` to `apps/xr-mobile/Assets/Scripts/Editor/AndroidBuild.cs:158`.
- E60 forces application ID `com.mlomega.xr.phoneonly` and regenerates the PhoneOnly scene on every build.
- The generated production scene now includes `PhoneOnlyReflexSignalSource`, `MenuPanel`, `OrientationGuard`, `TtsAudioPlayer` and panel-manipulation wiring in addition to the prior pairing/capture/transport/UI components.

tables read/write:

- Launcher no direct DB.
- SimOnly writes demo BrainLive/feedback DB; LivePhone runtime writes through flows above.

tests existing:

- `tests/v19/test_scripts_profile.py:7` script/profile presence.
- `tests/v19/test_phoneonly_android_wiring.py:43` PhoneOnly scene separate from G1 and includes components.
- `tests/v19/test_phoneonly_android_wiring.py:35` Android network/plugin export explicit.

tests missing:

- Actual Windows run of `-LivePhone` plus Unity Android build/install on device, confirming package ID and regenerated scene contents.
- Full installer/onboarding E2E with user profile, models, Unity Hub/JDK/Gradle/adb.

command:

```powershell
.\.venv-live\Scripts\python.exe -m pytest tests/v19/test_scripts_profile.py tests/v19/test_phoneonly_android_wiring.py
```

risks if modified:

- Keep `-SimOnly` and `-LivePhone` separated; fake device must not be launched by the PhoneOnly hardware path.
- Onboarding must not claim Unity/Android validation unless APK/AAR build and real phone test have run.
- Never allow a stale pre-E60 scene to bypass regeneration during an APK build.
