# reflexvision — MLOmega V19 Ultra-Live sensing (E26)

On-device Android library for the Ultra-Live reflex path. **Contains NO LLM and
NO VLM** (handoff §3.2) — only small specialised calculators that run in
< 100 ms on the device:

| Back-end | Library | Job |
|---|---|---|
| `GesturePipeline` | MediaPipe Tasks Vision `GestureRecognizer` (bundles HandLandmarker), `LIVE_STREAM` | pinch → continuous zoom (begin/update/end), open palm held → menu, lateral swipe → hide UI |
| `AsrKwsService` | sherpa-onnx: Silero VAD + streaming zipformer ASR + `KeywordSpotter` | FR/EN live subtitles (partial/final + timestamps) and a configurable wake word |

Produces an `.aar` vendored into the Unity app (`Assets/Plugins/Android`) and
driven from C# via `GestureBridge.cs` / `AsrBridge.cs`. It is only activated on
demand by the Unity `ReflexScheduler` (GUIDE_V19 §9.4 — never all detectors in
parallel; battery). Same conventions as the E24 `livetransport` module.

## Single-microphone arbitration + wake-word command window (E47-A)

There is exactly **one** microphone in the whole app. It lives in the
`livetransport` module: a `JavaAudioDeviceModule` with a samples-ready callback
whose captured PCM is (a) encoded to Opus for the WebRTC uplink and (b) fanned
out unchanged to a `PcmFeed`. `AsrKwsService` **does not own an `AudioRecord`** on
this path — it consumes those same samples via `asPcmSink()`, which the transport
attaches with `LiveTransportPlugin.attachPcmFeed(...)`. Two concurrent microphones
are forbidden. (A legacy self-owned `AudioRecord` path remains, gated by
`AsrKwsConfig.ownMicrophone=true`, for device-standalone bring-up with no WebRTC.)

The wake word only gates **routing**, never capture:

- The wake word is a **user-chosen word** (`MLOmegaConfig.WakeWord`, default
  `omega`), encoded by `KeywordEncoder` — no rebuild to change it.
- A KWS hit opens a **command window** of `AsrKwsConfig.commandWindowMs`
  (`MLOmegaConfig.CommandWindowSeconds`, default 6 s). Final ASR segments that end
  inside the window are flagged `isCommand=true` (`onTranscript(...)`), forwarded
  to the PC as the additive `is_command` field of the `device_transcript`
  DataChannel message (`LiveTransportBridge.SendTranscriptSegment`).
- **Capture is never stopped** — all audio keeps flowing to the PC (life memory /
  hot context); the wake word only tells the PC which segments to route as
  commands. Offline subtitles still render locally from the ASR results
  (SubtitleSkill, E26). The Silero VAD gates *ASR decoding* (battery) but not the
  uplink.

Both the fan-out (`MicAudioFanout`, livetransport) and the window timing
(`CommandWindow`, here) are pure and JVM-tested (`MicAudioFanoutTest`,
`CommandWindowTest`).

> **Build status:** this module cannot be compiled in the authoring environment
> (no Android SDK). It is written against the pinned APIs below; the real compile
> + on-device validation is the S25 gate (ADR `docs/DECISIONS.md` §E26). The pure
> logic (`GestureStateMachine`, `KeywordEncoder`) is covered by JVM unit tests in
> `src/test` and runs with plain `./gradlew test`.

## Pinned dependencies

| Dependency | Version | License | Source |
|---|---|---|---|
| `com.google.mediapipe:tasks-vision` | `0.10.29` | Apache-2.0 | Maven Central |
| `com.github.k2-fsa:sherpa-onnx-android` | `1.12.10` | Apache-2.0 | JitPack (or vendored static AAR, below) |
| `org.jetbrains.kotlinx:kotlinx-coroutines-android` | `1.8.1` | Apache-2.0 | Maven Central |

If a LAN-only build cannot reach JitPack, download the pre-built static AAR from
the sherpa-onnx GitHub release (`sherpa-onnx-v1.12.10-android.tar.bz2`), drop it
in `libs/`, and swap the dependency to
`implementation(files("libs/sherpa-onnx.aar"))`.

## Models (NOT committed — download to app storage at first run)

Weights are never checked in. Install them under the app's files dir and pass the
absolute directories in `AsrKwsConfig` / `GestureConfig`.

### Gestures (MediaPipe `.task` bundles) — E47-B

Provisioned at first run into the app-private **external** files dir
(`getExternalFilesDir(null)/models/`, no permission required), never shipped in
the APK (E47 device provisioning, livrable 2). The Unity `GestureBridge`
resolves `getExternalFilesDir(null)/models/gesture_recognizer.task` and passes it
as `GestureConfig.modelAssetPath`.

- `gesture_recognizer.task` (bundles the HandLandmarker — the pipeline runs a
  single `GestureRecognizer` graph, so this one bundle already yields both the
  hand landmarks and the discrete gesture category)
  <https://storage.googleapis.com/mediapipe-models/gesture_recognizer/gesture_recognizer/float16/latest/gesture_recognizer.task>
  → install to `getExternalFilesDir(null)/models/gesture_recognizer.task`
  → `GestureConfig.modelAssetPath`
- `hand_landmarker.task` (landmarks-only; provisioned alongside for a future
  landmarker-only path / diagnostics — not required by the current
  `GestureRecognizer` graph)
  <https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task>
  → install to `getExternalFilesDir(null)/models/hand_landmarker.task`

> **Cadence (E47-B):** the Unity capture texture (the same frame WebRTC sends)
> is subscribed via `EyeCaptureSource.OnFrame`, downscaled to 256 px on its long
> side, and pushed to `GesturePipeline.pushFrame` throttled to **10–15 fps**
> (`FrameThrottle`, default 12 fps) — never at full capture resolution or 30 fps.
> Frames are only fed while the `ReflexScheduler` has activated the pipeline
> (GUIDE_V19 §9.4 — battery); `FrameThrottle` on the native side is the
> authoritative drop policy and is JVM-tested (`FrameThrottleTest`).

### ASR — streaming zipformer (choose by language)

- **EN**: `sherpa-onnx-streaming-zipformer-en-2023-06-26`
  <https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-streaming-zipformer-en-2023-06-26.tar.bz2>
- **FR**: `sherpa-onnx-streaming-zipformer-fr-2023-04-14`
  <https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-streaming-zipformer-fr-2023-04-14.tar.bz2>

Extract to `<filesDir>/reflex/asr-<lang>/` so that `encoder.onnx`, `decoder.onnx`,
`joiner.onnx`, `tokens.txt` sit directly inside → `AsrKwsConfig.asrModelDir`.

### VAD (Silero)

- `silero_vad.onnx`
  <https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/silero_vad.onnx>
  → `<filesDir>/reflex/silero_vad.onnx` → `AsrKwsConfig.vadModelPath`

### Wake word — KeywordSpotter (streaming zipformer KWS)

- `sherpa-onnx-kws-zipformer-gigaspeech-3.3M-2024-01-01` (English wake words)
  <https://github.com/k2-fsa/sherpa-onnx/releases/download/kws-models/sherpa-onnx-kws-zipformer-gigaspeech-3.3M-2024-01-01.tar.bz2>

Extract to `<filesDir>/reflex/kws/` → `AsrKwsConfig.kwsModelDir`. The wake phrase
itself is **configurable** (from `MLOmegaConfig` on the Unity side): it is encoded
at runtime by `KeywordEncoder` into the sherpa keywords file the spotter loads, so
changing the wake word needs no rebuild and no new model.

> The KWS model ships a `bpe.model`; for phrases outside its whole-word vocabulary,
> pre-tokenise once with `sherpa-onnx-cli text2token --tokens tokens.txt
> --tokens-type bpe --bpe-model bpe.model "hey mlomega" out.txt` and pass the
> resulting token string as the wake word (it is passed through verbatim).

## Permissions

The library manifest declares `RECORD_AUDIO`, `FOREGROUND_SERVICE` and
`FOREGROUND_SERVICE_MICROPHONE`, and the `MicForegroundService` that holds the
background-mic slot with a privacy-visible notification (GUIDE_V19 §15.2). Camera
frames for MediaPipe come from the Unity capture path, so this library does not
request `CAMERA`.
