package com.mlomega.xr.reflexvision

import android.content.Context
import android.graphics.Bitmap
import android.util.Log
import com.google.mediapipe.framework.image.BitmapImageBuilder
import com.google.mediapipe.framework.image.MPImage
import com.google.mediapipe.tasks.core.BaseOptions
import com.google.mediapipe.tasks.core.Delegate
import com.google.mediapipe.tasks.vision.core.RunningMode
import com.google.mediapipe.tasks.vision.handlandmarker.HandLandmarker
import com.google.mediapipe.tasks.vision.handlandmarker.HandLandmarkerResult
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.math.sqrt

/**
 * Pinch-only Eye path for XREAL One Pro + Eye.
 *
 * Deliberately separate from [GesturePipeline]: the product gesture recognizer
 * remains unchanged, while the Atelier uses the lighter HandLandmarker path
 * proven on this exact glasses/camera family by Xreal-tools. Detection follows
 * the same robust geometry: 3D distance(thumb tip,index tip) divided by
 * distance(wrist,index MCP), EMA 0.5, hysteresis 0.28/0.38 and 3/2-frame
 * asymmetric debounce. Apache-2.0 reference:
 * https://github.com/nudou350/Xreal-tools
 */
class EyePinchPipeline(
    private val appContext: Context,
    private val config: GestureConfig,
    private val callbacks: GestureCallbacks,
) {
    private val running = AtomicBoolean(false)
    private val throttle = FrameThrottle.forTargetFps(config.targetFps)

    @Volatile
    private var landmarker: HandLandmarker? = null
    private var ema = Float.NaN
    private var pinched = false
    private var candidate: Boolean? = null
    private var candidateFrames = 0
    private var missingFrames = 0
    private var resultCount = 0L
    private var lastDiagnosticMs = Long.MIN_VALUE

    fun start() {
        if (!running.compareAndSet(false, true)) return
        throttle.reset()
        resetPinch()
        try {
            val base = BaseOptions.builder()
                .setModelAssetPath(config.modelAssetPath)
                .setDelegate(Delegate.GPU)
                .build()
            val options = HandLandmarker.HandLandmarkerOptions.builder()
                .setBaseOptions(base)
                .setRunningMode(RunningMode.LIVE_STREAM)
                .setNumHands(config.numHands)
                .setMinHandDetectionConfidence(config.minHandDetectionConfidence)
                .setMinHandPresenceConfidence(config.minHandPresenceConfidence)
                .setMinTrackingConfidence(config.minTrackingConfidence)
                .setResultListener(::onResult)
                .setErrorListener { e -> callbacks.onError("eye pinch: ${e.message}") }
                .build()
            landmarker = HandLandmarker.createFromOptions(appContext, options)
            Log.i(TAG, "HandLandmarker ready (GPU/LIVE_STREAM, ${config.targetFps} fps)")
        } catch (t: Throwable) {
            running.set(false)
            callbacks.onError("eye pinch start failed: ${t.message}")
        }
    }

    fun stop() {
        if (!running.compareAndSet(true, false)) return
        try {
            landmarker?.close()
        } catch (t: Throwable) {
            callbacks.onError("eye pinch stop failed: ${t.message}")
        } finally {
            landmarker = null
            resetPinch()
        }
    }

    fun isRunning(): Boolean = running.get()

    fun pushFrame(bitmap: Bitmap, timestampMs: Long) {
        val tracker = landmarker ?: return
        if (!throttle.accept(timestampMs)) return
        val image: MPImage = BitmapImageBuilder(bitmap).build()
        try {
            tracker.detectAsync(image, timestampMs)
        } catch (t: Throwable) {
            image.close()
            callbacks.onError("eye pinch frame failed: ${t.message}")
        }
    }

    private fun onResult(result: HandLandmarkerResult, image: MPImage) {
        try {
            resultCount++
            val ts = result.timestampMs()
            val hands = result.landmarks()
            if (hands.isEmpty() || hands[0].size <= INDEX_TIP) {
                missingFrames++
                if (pinched && missingFrames >= RELEASE_FRAMES) {
                    callbacks.onGesture(GestureKind.PINCH_END, 1f, -1f, -1f, ts)
                    resetPinch()
                }
                logDiagnostic(ts, false, 1f, -1f, -1f)
                return
            }
            missingFrames = 0
            val hand = hands[0]
            val thumb = hand[THUMB_TIP]
            val index = hand[INDEX_TIP]
            val wrist = hand[WRIST]
            val indexMcp = hand[INDEX_MCP]
            val scale = dist3(wrist.x(), wrist.y(), wrist.z(), indexMcp.x(), indexMcp.y(), indexMcp.z())
            val raw = dist3(thumb.x(), thumb.y(), thumb.z(), index.x(), index.y(), index.z())
            val ratio = if (scale > 1e-4f) raw / scale else raw
            ema = if (ema.isNaN()) ratio else EMA_ALPHA * ratio + (1f - EMA_ALPHA) * ema
            val x = (thumb.x() + index.x()) * .5f
            val y = (thumb.y() + index.y()) * .5f
            evaluatePinch(ema, x, y, ts)
            logDiagnostic(ts, true, ema, x, y)
        } finally {
            image.close()
        }
    }

    private fun evaluatePinch(ratio: Float, x: Float, y: Float, ts: Long) {
        val want = when {
            !pinched && ratio < ENTER_THRESHOLD -> true
            pinched && ratio > EXIT_THRESHOLD -> false
            else -> {
                candidate = null
                candidateFrames = 0
                if (pinched) callbacks.onGesture(
                    GestureKind.PINCH_UPDATE,
                    zoomFor(ratio), x, y, ts,
                )
                return
            }
        }
        if (candidate != want) {
            candidate = want
            candidateFrames = 0
        }
        candidateFrames++
        val required = if (want) ENGAGE_FRAMES else RELEASE_FRAMES
        if (candidateFrames < required) return
        pinched = want
        candidate = null
        candidateFrames = 0
        callbacks.onGesture(
            if (want) GestureKind.PINCH_BEGIN else GestureKind.PINCH_END,
            if (want) zoomFor(ratio) else 1f,
            x, y, ts,
        )
    }

    private fun zoomFor(ratio: Float): Float {
        val p = config.pinch
        val t = ((ratio - p.closedNormalizedDistance) /
            (p.openNormalizedDistance - p.closedNormalizedDistance)).coerceIn(0f, 1f)
        return p.zoomAtMinDistance + t * (p.zoomAtMaxDistance - p.zoomAtMinDistance)
    }

    private fun resetPinch() {
        ema = Float.NaN
        pinched = false
        candidate = null
        candidateFrames = 0
        missingFrames = 0
    }

    private fun logDiagnostic(ts: Long, hand: Boolean, ratio: Float, x: Float, y: Float) {
        if (lastDiagnosticMs == Long.MIN_VALUE || ts - lastDiagnosticMs >= 1000L) {
            lastDiagnosticMs = ts
            Log.i(TAG, "results=$resultCount hand=$hand ratio=$ratio anchor=($x,$y)")
        }
    }

    private fun dist3(ax: Float, ay: Float, az: Float, bx: Float, by: Float, bz: Float): Float {
        val dx = ax - bx
        val dy = ay - by
        val dz = az - bz
        return sqrt(dx * dx + dy * dy + dz * dz)
    }

    companion object {
        private const val TAG = "MLOmegaEyePinch"
        private const val WRIST = 0
        private const val THUMB_TIP = 4
        private const val INDEX_MCP = 5
        private const val INDEX_TIP = 8
        private const val ENTER_THRESHOLD = .28f
        private const val EXIT_THRESHOLD = .38f
        private const val EMA_ALPHA = .5f
        private const val ENGAGE_FRAMES = 3
        private const val RELEASE_FRAMES = 2
    }
}
