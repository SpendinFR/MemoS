package com.mlomega.xr.reflexvision

import android.content.Context
import com.google.mediapipe.tasks.audio.audioclassifier.AudioClassifier
import com.google.mediapipe.tasks.audio.core.RunningMode
import com.google.mediapipe.tasks.components.containers.AudioData
import com.google.mediapipe.tasks.core.BaseOptions
import java.io.File
import java.io.FileInputStream
import java.nio.MappedByteBuffer
import java.nio.channels.FileChannel
import java.util.Locale
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean

/**
 * Opt-in YAMNet sound event classifier fed by the transport microphone fan-out.
 *
 * The audio callback only downmixes/resamples/copies. One keep-only-latest worker
 * performs inference, so sound recognition cannot stall WebRTC or open another
 * microphone. Direction is deliberately absent: one phone microphone cannot
 * provide a defensible bearing.
 */
class SemanticSoundClassifier(
    context: Context,
    modelPath: String,
    private val callbacks: SemanticSoundCallbacks,
    private val minimumScore: Float = 0.45f,
    cooldownMs: Long = 8_000L,
) {
    private val lock = Any()
    private val executor = Executors.newSingleThreadExecutor()
    private val inFlight = AtomicBoolean(false)
    private val cooldownMs = cooldownMs.coerceAtLeast(1_000L)
    private val buffer = FloatArray(INPUT_SAMPLES)
    private var bufferSize = 0
    private var phase = 0
    private var closed = false
    private val lastEmitted = mutableMapOf<String, Long>()

    // MediaPipe requires an Android asset path or a direct buffer. Provisioned
    // device models live in external files, so map that verified file once.
    private val modelBuffer: MappedByteBuffer
    private val classifier: AudioClassifier

    init {
        val modelFile = File(modelPath)
        require(modelFile.isFile) { "YAMNet model missing: $modelPath" }
        modelBuffer = FileInputStream(modelFile).channel.use { channel ->
            channel.map(FileChannel.MapMode.READ_ONLY, 0, channel.size())
        }
        val options = AudioClassifier.AudioClassifierOptions.builder()
            .setBaseOptions(BaseOptions.builder().setModelAssetBuffer(modelBuffer).build())
            .setRunningMode(RunningMode.AUDIO_CLIPS)
            .setScoreThreshold(0.25f)
            .setMaxResults(8)
            .build()
        classifier = AudioClassifier.createFromOptions(context, options)
    }

    /** Shape-compatible with livetransport.PcmFeed; Unity attaches it once. */
    fun asPcmSink(): PcmFeed = object : PcmFeed {
        override fun onPcm(
            samples: ShortArray,
            sampleCount: Int,
            sampleRate: Int,
            channels: Int,
            timestampMs: Long,
        ) {
            pushPcm(samples, sampleCount, sampleRate, channels, timestampMs)
        }
    }

    private fun pushPcm(
        samples: ShortArray,
        sampleCount: Int,
        sampleRate: Int,
        channels: Int,
        timestampMs: Long,
    ) {
        if (sampleRate <= 0 || channels <= 0 || sampleCount <= 0) return
        var ready: FloatArray? = null
        synchronized(lock) {
            if (closed) return
            val frames = (sampleCount.coerceAtMost(samples.size) / channels)
            for (frame in 0 until frames) {
                phase += TARGET_RATE
                if (phase < sampleRate) continue
                phase -= sampleRate
                var mixed = 0
                val base = frame * channels
                for (channel in 0 until channels) mixed += samples[base + channel].toInt()
                buffer[bufferSize++] =
                    (mixed.toFloat() / channels.toFloat() / Short.MAX_VALUE.toFloat())
                        .coerceIn(-1f, 1f)
                if (bufferSize == buffer.size) {
                    ready = buffer.copyOf()
                    bufferSize = 0
                    break
                }
            }
        }
        val clip = ready ?: return
        if (!inFlight.compareAndSet(false, true)) return
        executor.execute {
            try {
                classify(clip, timestampMs)
            } catch (error: Exception) {
                callbacks.onError(error.message ?: error.javaClass.simpleName)
            } finally {
                inFlight.set(false)
            }
        }
    }

    private fun classify(samples: FloatArray, timestampMs: Long) {
        val format = AudioData.AudioDataFormat.builder()
            .setNumOfChannels(1)
            .setSampleRate(TARGET_RATE.toFloat())
            .build()
        val data = AudioData.create(format, samples.size)
        data.load(samples)
        val result = classifier.classify(data)
        val candidates = result.classificationResults()
            .flatMap { it.classifications() }
            .flatMap { it.categories() }
            .mapNotNull { category ->
                val canonical = canonicalLabel(category.categoryName()) ?: return@mapNotNull null
                canonical to category.score()
            }
            .filter { candidate -> candidate.second >= thresholdFor(candidate.first) }
            .sortedByDescending { it.second }
        val best = candidates.firstOrNull() ?: return
        synchronized(lock) {
            val previous = lastEmitted[best.first] ?: Long.MIN_VALUE
            if (timestampMs - previous < cooldownMs) return
            lastEmitted[best.first] = timestampMs
        }
        callbacks.onSound(best.first, best.second, timestampMs)
    }

    private fun thresholdFor(it: String): Float {
        val categoryFloor = when (it) {
            "glass_breaking", "smoke_alarm", "siren" -> 0.35f
            "doorbell", "baby_cry", "dog_bark" -> 0.40f
            else -> 0.50f
        }
        return maxOf(minimumScore, categoryFloor)
    }

    fun close() {
        synchronized(lock) {
            if (closed) return
            closed = true
        }
        executor.shutdownNow()
        classifier.close()
    }

    companion object {
        private const val TARGET_RATE = 16_000
        private const val INPUT_SAMPLES = 15_600 // YAMNet: 0.975 s at 16 kHz.

        private fun canonicalLabel(raw: String?): String? {
            val label = raw.orEmpty().lowercase(Locale.ROOT)
            return when {
                "glass" in label && ("break" in label || "shatter" in label) ->
                    "glass_breaking"
                "smoke detector" in label || "smoke alarm" in label ->
                    "smoke_alarm"
                "siren" in label -> "siren"
                "doorbell" in label -> "doorbell"
                "baby cry" in label || "infant cry" in label -> "baby_cry"
                "dog" in label && ("bark" in label || "howl" in label) -> "dog_bark"
                "engine" in label || "motor vehicle" in label -> "engine"
                "footstep" in label || "walk" in label -> "footsteps"
                else -> null
            }
        }
    }
}
