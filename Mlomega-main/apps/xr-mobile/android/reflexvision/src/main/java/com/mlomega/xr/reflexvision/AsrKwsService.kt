package com.mlomega.xr.reflexvision

import android.content.Context
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import com.k2fsa.sherpa.onnx.FeatureConfig
import com.k2fsa.sherpa.onnx.KeywordSpotter
import com.k2fsa.sherpa.onnx.KeywordSpotterConfig
import com.k2fsa.sherpa.onnx.OnlineModelConfig
import com.k2fsa.sherpa.onnx.OnlineRecognizer
import com.k2fsa.sherpa.onnx.OnlineRecognizerConfig
import com.k2fsa.sherpa.onnx.OnlineTransducerModelConfig
import com.k2fsa.sherpa.onnx.Vad
import com.k2fsa.sherpa.onnx.VadModelConfig
import com.k2fsa.sherpa.onnx.getFeatureConfig
import java.io.File
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.concurrent.thread

/**
 * MLOmega V19 on-device speech pipeline (E26 + E47-A).
 *
 * Three sherpa-onnx calculators run in parallel over a 16 kHz mono PCM stream
 * (handoff §3.2 — **NO LLM / NO VLM**, all small on-device models, < 100 ms):
 *   * a Silero [Vad] gates the ASR so decoding runs only inside speech (battery);
 *   * a streaming zipformer [OnlineRecognizer] (FR *or* EN, chosen by config)
 *     emits partial + final transcripts with timestamps → SubtitleSkill;
 *   * a [KeywordSpotter] watches for the configurable wake word → WakeWordGate.
 *
 * **E47-A single-microphone arbitration.** By default the service does NOT own a
 * microphone: it consumes the SAME PCM the WebRTC transport captures via
 * [asPcmSink] (a [PcmFeed] the livetransport `JavaAudioDeviceModule` fans out).
 * Two concurrent microphones are forbidden. A legacy self-owned [AudioRecord]
 * path (E26, no WebRTC) remains available via [AsrKwsConfig.ownMicrophone] for
 * device-standalone bring-up.
 *
 * **Wake-word command window.** Capture NEVER stops — all audio keeps flowing to
 * the PC (life memory / hot context). The wake word only gates *routing*: it
 * opens a command window of [AsrKwsConfig.commandWindowMs]; final transcripts
 * that end inside that window are flagged `isCommand=true` so the PC routes them
 * as commands, while everything outside stays plain memory.
 *
 * **On-demand (GUIDE_V19_REFERENCE §9.4):** the models are created on [start] and
 * released on [stop]; the Unity ReflexScheduler / WakeWordGate call these. A
 * [MicForegroundService] holds the background-mic slot only when this service
 * owns the microphone (legacy path).
 *
 * Model files are loaded from app storage (paths in [AsrKwsConfig]); weights are
 * never committed (download URLs + install layout in the README).
 *
 * This module cannot be compiled in the authoring environment (no Android SDK);
 * it is written against the pinned sherpa-onnx Android API (see build.gradle.kts)
 * and the real compile/run belongs to the S25 validation gate
 * (ADR docs/DECISIONS §E26/§E47).
 */
class AsrKwsService(
    private val appContext: Context,
    private val config: AsrKwsConfig,
    private val callbacks: AsrKwsCallbacks,
) {
    private val running = AtomicBoolean(false)

    @Volatile private var recognizer: OnlineRecognizer? = null
    @Volatile private var vad: Vad? = null
    @Volatile private var spotter: KeywordSpotter? = null
    @Volatile private var audioRecord: AudioRecord? = null
    @Volatile private var worker: Thread? = null

    /** Lazily created KWS stream, reused across chunks (external + legacy paths). */
    @Volatile private var kwsStream: com.k2fsa.sherpa.onnx.OnlineStream? = null

    /** Start of the currently open VAD speech segment, or -1 when idle. */
    @Volatile private var segmentStartMs: Long = -1L

    /** Whether the wake word is currently armed (KWS enabled). */
    private val kwsArmed = AtomicBoolean(true)

    /**
     * E47-A command window: a wake-word hit opens it for
     * [AsrKwsConfig.commandWindowMs]; finals ending inside are flagged
     * `isCommand`. Capture itself is never affected — routing only.
     */
    private val commandWindow = CommandWindow(config.commandWindowMs)

    /**
     * Build the models + calculators and begin processing.
     *
     * With [AsrKwsConfig.ownMicrophone]==false (E47-A default) the service does
     * NOT open a microphone: it waits for PCM pushed through [asPcmSink] by the
     * transport's fan-out. With `ownMicrophone`==true (legacy E26, no WebRTC) it
     * opens its own [AudioRecord]. No-op if already running.
     */
    fun start() {
        if (!running.compareAndSet(false, true)) return
        try {
            buildModels()
            kwsStream = spotter!!.createStream()
            segmentStartMs = -1L
            if (config.ownMicrophone) {
                MicForegroundService.start(appContext)
                startAudioLoop()
            }
            // External-feed mode: nothing else to start; onPcm() drives processing.
        } catch (t: Throwable) {
            running.set(false)
            release()
            callbacks.onError("asr start failed: ${t.message}")
        }
    }

    /** Stop processing, release models (and the mic if owned), stop the service. */
    fun stop() {
        if (!running.compareAndSet(true, false)) return
        try {
            worker?.join(500)
        } catch (_: InterruptedException) {
        }
        worker = null
        commandWindow.close()
        release()
        if (config.ownMicrophone) MicForegroundService.stop(appContext)
    }

    fun isRunning(): Boolean = running.get()

    /** Arm/disarm the wake-word spotter without tearing down ASR (e.g. while a command is being taken). */
    fun setWakeWordArmed(armed: Boolean) = kwsArmed.set(armed)

    /**
     * E47-A — the [PcmFeed] the transport fan-out pushes microphone PCM into.
     * Wire `LiveTransportPlugin.attachPcmFeed(asrKwsService.asPcmSink())` so the
     * WebRTC-captured audio drives the on-device pipeline with no second mic.
     */
    fun asPcmSink(): PcmFeed = object : PcmFeed {
        override fun onPcm(
            samples: ShortArray,
            sampleCount: Int,
            sampleRate: Int,
            channels: Int,
            timestampMs: Long,
        ) = onExternalPcm(samples, sampleCount, sampleRate, channels, timestampMs)
    }

    /**
     * E47-A — open the command window for [AsrKwsConfig.commandWindowMs] starting
     * at [nowMs]. Called on a wake-word hit (device-side) so subsequent final
     * transcripts are flagged as commands. Capture is unaffected — this only tags
     * routing. Idempotent within a window (a fresh hit re-extends it).
     */
    fun openCommandWindow(nowMs: Long = System.currentTimeMillis()) = commandWindow.open(nowMs)

    /** Force-close the command window early (e.g. after a command was captured). */
    fun closeCommandWindow() = commandWindow.close()

    /** Whether [endMs] falls inside an open command window (final → `isCommand`). */
    internal fun isWithinCommandWindow(endMs: Long): Boolean = commandWindow.isOpenAt(endMs)

    // ----------------------------------------------------------------------
    //  Model construction
    // ----------------------------------------------------------------------

    private fun buildModels() {
        val feat: FeatureConfig = getFeatureConfig(sampleRate = config.sampleRate, featureDim = 80)

        val transducer = OnlineTransducerModelConfig(
            encoder = File(config.asrModelDir, "encoder.onnx").absolutePath,
            decoder = File(config.asrModelDir, "decoder.onnx").absolutePath,
            joiner = File(config.asrModelDir, "joiner.onnx").absolutePath,
        )
        val modelConfig = OnlineModelConfig(
            transducer = transducer,
            tokens = File(config.asrModelDir, "tokens.txt").absolutePath,
            numThreads = config.numThreads,
            provider = config.provider,
        )
        val recognizerConfig = OnlineRecognizerConfig(
            featConfig = feat,
            modelConfig = modelConfig,
            enableEndpoint = true,
        )
        recognizer = OnlineRecognizer(config = recognizerConfig)

        val vadConfig = VadModelConfig(
            sileroVadModelConfig = com.k2fsa.sherpa.onnx.SileroVadModelConfig(
                model = config.vadModelPath,
                threshold = config.vad.threshold,
                minSilenceDuration = config.vad.minSilenceDurationSec,
                minSpeechDuration = config.vad.minSpeechDurationSec,
            ),
            sampleRate = config.sampleRate,
            numThreads = config.numThreads,
            provider = config.provider,
        )
        vad = Vad(config = vadConfig)

        // KeywordSpotter: streaming zipformer transducer over the encoded wake word.
        val keywordsFile = writeKeywordsFile()
        val kwsModel = OnlineModelConfig(
            transducer = OnlineTransducerModelConfig(
                encoder = File(config.kwsModelDir, "encoder.onnx").absolutePath,
                decoder = File(config.kwsModelDir, "decoder.onnx").absolutePath,
                joiner = File(config.kwsModelDir, "joiner.onnx").absolutePath,
            ),
            tokens = File(config.kwsModelDir, "tokens.txt").absolutePath,
            numThreads = config.numThreads,
            provider = config.provider,
        )
        val kwsConfig = KeywordSpotterConfig(
            featConfig = feat,
            modelConfig = kwsModel,
            keywordsFile = keywordsFile.absolutePath,
            keywordsScore = config.kws.keywordsScore,
            keywordsThreshold = config.kws.keywordsThreshold,
            maxActivePaths = config.kws.maxActivePaths,
            numTrailingBlanks = config.kws.numTrailingBlanks,
        )
        spotter = KeywordSpotter(config = kwsConfig)
    }

    /**
     * Encode the configured wake phrase(s) into a sherpa keywords file on app
     * storage. Regenerated each start so a config change takes effect without any
     * committed asset.
     */
    private fun writeKeywordsFile(): File {
        val contents = KeywordEncoder.encode(
            phrases = config.wakeWords,
            boost = config.kws.keywordsScore,
            threshold = config.kws.keywordsThreshold,
        )
        val file = File(appContext.filesDir, "reflex_wake_keywords.txt")
        file.writeText(contents)
        return file
    }

    // ----------------------------------------------------------------------
    //  E47-A external feed: same PCM WebRTC captured, no second microphone
    // ----------------------------------------------------------------------

    /**
     * Consume one PCM buffer pushed by the transport fan-out. Downmixes to mono
     * if needed and drives the same VAD-gated ASR + KWS as the legacy loop.
     * Ignored unless [running]; safe if a buffer arrives before [start] completes.
     */
    private fun onExternalPcm(
        samples: ShortArray,
        sampleCount: Int,
        sampleRate: Int,
        channels: Int,
        timestampMs: Long,
    ) {
        if (!running.get()) return
        val mono = toMonoFloat(samples, sampleCount, channels)
        processChunk(mono, sampleRate, timestampMs)
    }

    /**
     * Convert interleaved 16-bit PCM to mono float in [-1, 1]. Multi-channel
     * input is averaged across channels. Pure/JVM-testable helper.
     */
    private fun toMonoFloat(samples: ShortArray, sampleCount: Int, channels: Int): FloatArray {
        if (channels <= 1) {
            return FloatArray(sampleCount) { samples[it] / 32768.0f }
        }
        val frames = sampleCount / channels
        return FloatArray(frames) { f ->
            var acc = 0
            for (c in 0 until channels) acc += samples[f * channels + c].toInt()
            (acc.toFloat() / channels) / 32768.0f
        }
    }

    // ----------------------------------------------------------------------
    //  Legacy audio loop (E26): self-owned AudioRecord, no WebRTC
    // ----------------------------------------------------------------------

    private fun startAudioLoop() {
        val minBuf = AudioRecord.getMinBufferSize(
            config.sampleRate,
            AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT,
        )
        val bufferSize = maxOf(minBuf, config.sampleRate / 5 * 2) // ~200 ms floor
        val record = AudioRecord(
            MediaRecorder.AudioSource.VOICE_RECOGNITION,
            config.sampleRate,
            AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT,
            bufferSize,
        )
        audioRecord = record

        val chunk = ShortArray(config.sampleRate / 10) // 100 ms chunks

        worker = thread(name = "mlomega-asr-kws", isDaemon = true) {
            record.startRecording()
            while (running.get()) {
                val n = record.read(chunk, 0, chunk.size)
                if (n <= 0) continue
                val samples = FloatArray(n) { chunk[it] / 32768.0f }
                processChunk(samples, config.sampleRate, System.currentTimeMillis())
            }
            try { record.stop() } catch (_: Throwable) {}
        }
    }

    // ----------------------------------------------------------------------
    //  Shared processing: VAD-gated ASR + KWS over one float PCM chunk
    // ----------------------------------------------------------------------

    /**
     * Process one mono float PCM chunk: run the wake-word spotter (opening the
     * command window on a hit) and the VAD-gated ASR. Shared by the external-feed
     * (E47-A) and legacy AudioRecord (E26) paths. Synchronized so overlapping
     * feed callbacks never touch the sherpa streams concurrently.
     */
    @Synchronized
    private fun processChunk(samples: FloatArray, sampleRate: Int, nowMs: Long) {
        // --- wake word ---
        if (kwsArmed.get()) {
            val s = spotter
            val ks = kwsStream
            if (s != null && ks != null) {
                ks.acceptWaveform(samples, sampleRate = sampleRate)
                while (s.isReady(ks)) {
                    s.decode(ks)
                    val kw = s.getResult(ks).keyword
                    if (kw.isNotEmpty()) {
                        s.reset(ks)
                        openCommandWindow(nowMs) // gate ROUTING only; capture continues
                        callbacks.onWakeWord(kw, nowMs)
                    }
                }
            }
        }

        // --- VAD-gated ASR ---
        val v = vad ?: return
        v.acceptWaveform(samples)
        if (v.isSpeechDetected() && segmentStartMs < 0L) segmentStartMs = nowMs
        while (!v.empty()) {
            val segment = v.front()
            decodeSegment(segment.samples, segmentStartMs, nowMs, sampleRate)
            v.pop()
            segmentStartMs = -1L
        }
    }

    private fun decodeSegment(samples: FloatArray, startMs: Long, endMs: Long, sampleRate: Int) {
        val r = recognizer ?: return
        val stream = r.createStream()
        try {
            stream.acceptWaveform(samples, sampleRate = sampleRate)
            while (r.isReady(stream)) {
                r.decode(stream)
                val partial = r.getResult(stream).text
                if (partial.isNotBlank()) {
                    // Partials are never commands — only the final decides routing.
                    callbacks.onTranscript(partial, false, langCode(), startMs, endMs, false)
                }
            }
            stream.inputFinished()
            while (r.isReady(stream)) {
                r.decode(stream)
            }
            val finalText = r.getResult(stream).text
            if (finalText.isNotBlank()) {
                // E47-A: a final that ends inside the wake-word window routes as a
                // command; capture already went to the PC regardless.
                val isCommand = isWithinCommandWindow(endMs)
                callbacks.onTranscript(finalText, true, langCode(), startMs, endMs, isCommand)
            }
        } finally {
            stream.release()
        }
    }

    private fun langCode(): String = if (config.language == AsrLanguage.FR) "fr" else "en"

    private fun release() {
        try { audioRecord?.release() } catch (_: Throwable) {}
        audioRecord = null
        try { kwsStream?.release() } catch (_: Throwable) {}
        kwsStream = null
        try { recognizer?.release() } catch (_: Throwable) {}
        recognizer = null
        try { spotter?.release() } catch (_: Throwable) {}
        spotter = null
        try { vad?.release() } catch (_: Throwable) {}
        vad = null
    }
}
