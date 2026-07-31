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
 * distance(wrist,index MCP), EMA 0.5, hysteresis 0.28/0.38 and 2/2-frame
 * asymmetric debounce. A held, fully-open palm also emits the existing
 * OPEN_PALM_MENU contract without loading the heavier GestureRecognizer.
 * Apache-2.0 reference:
 * https://github.com/nudou350/Xreal-tools
 */
class EyePinchPipeline(
    private val appContext: Context,
    private val config: GestureConfig,
    private val callbacks: GestureCallbacks,
) {
    private val running = AtomicBoolean(false)
    private val throttle = FrameThrottle.forTargetFps(
        config.targetFps,
        MAX_ATELIER_FPS,
    )

    @Volatile
    private var landmarker: HandLandmarker? = null
    private var ema = Float.NaN
    private var pinched = false
    private var candidate: Boolean? = null
    private var candidateFrames = 0
    private var missingFrames = 0
    private var resultCount = 0L
    private var lastDiagnosticMs = Long.MIN_VALUE
    private var palmSinceMs = -1L
    private var palmFired = false
    private var twoPalmSinceMs = -1L
    private var twoPalmFired = false
    private var fistSinceMs = -1L
    private var fistFired = false

    fun start() {
        if (!running.compareAndSet(false, true)) return
        throttle.reset()
        resetPinch()
        resetFist()
        resetTwoPalm()
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
            resetFist()
            resetTwoPalm()
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
                resetPalm()
                resetFist()
                resetTwoPalm()
                if (pinched && missingFrames >= RELEASE_FRAMES) {
                    callbacks.onGesture(GestureKind.PINCH_END, 1f, -1f, -1f, ts)
                    resetPinch()
                }
                logDiagnostic(ts, false, 1f, -1f, -1f)
                return
            }
            missingFrames = 0
            val openHands = if (!pinched && candidate != true) {
                hands.filter { candidateHand ->
                    candidateHand.size > PINKY_TIP &&
                        isOpenPalmGeometry(candidateHand)
                }
            } else {
                emptyList()
            }
            val suppressSinglePalm = hands.size >= 2
            if (suppressSinglePalm) {
                // When both hands are visible, do not accidentally fire the
                // one-palm recenter. The dock requires two genuinely open palms.
                resetPalm()
                if (openHands.size >= 2) {
                    val left = openHands[0][WRIST]
                    val right = openHands[1][WRIST]
                    evaluateTwoPalm(
                        true,
                        (left.x() + right.x()) * .5f,
                        (left.y() + right.y()) * .5f,
                        ts,
                    )
                    resetFist()
                    logDiagnostic(ts, true, ema, -1f, -1f)
                    return
                }
            }
            resetTwoPalm()
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
            val closedFist = isClosedFist(hand)
            evaluateFist(closedFist, x, y, ts)
            if (closedFist) {
                resetPalm()
                if (pinched) {
                    callbacks.onGesture(GestureKind.PINCH_END, 1f, x, y, ts)
                    pinched = false
                    candidate = null
                    candidateFrames = 0
                }
                logDiagnostic(ts, true, ema, x, y)
                return
            }
            // The EMA keeps ordinary/noisy pinches stable, but a physically very
            // deep raw pinch is already unambiguous and must not wait for the EMA
            // to decay over several inference results.
            val decisionRatio = if (!pinched && ratio <= DEEP_RAW_ENTER_THRESHOLD) {
                ratio
            } else {
                ema
            }
            evaluatePinch(decisionRatio, x, y, ts)
            if (suppressSinglePalm) {
                resetPalm()
            } else {
                evaluatePalm(isOpenPalm(hand), x, y, ts)
            }
            logDiagnostic(ts, true, ema, x, y)
        } finally {
            image.close()
        }
    }

    /**
     * Rotation-independent open-palm check. Each of the four long fingers must
     * be straight at its PIP joint and extend away from the wrist. Requiring all
     * four fingers, a non-pinched hand and a timed hold avoids opening the deck
     * during an ordinary point or click.
     */
    private fun isOpenPalm(hand: List<com.google.mediapipe.tasks.components.containers.NormalizedLandmark>): Boolean {
        if (pinched || candidate == true || hand.size <= PINKY_TIP) return false
        return isOpenPalmGeometry(hand)
    }

    private fun isOpenPalmGeometry(
        hand: List<com.google.mediapipe.tasks.components.containers.NormalizedLandmark>,
    ): Boolean {
        if (hand.size <= PINKY_TIP) return false
        val wrist = hand[WRIST]

        fun extended(mcpIndex: Int, pipIndex: Int, tipIndex: Int): Boolean {
            val mcp = hand[mcpIndex]
            val pip = hand[pipIndex]
            val tip = hand[tipIndex]
            val aX = mcp.x() - pip.x()
            val aY = mcp.y() - pip.y()
            val aZ = mcp.z() - pip.z()
            val bX = tip.x() - pip.x()
            val bY = tip.y() - pip.y()
            val bZ = tip.z() - pip.z()
            val aLen = sqrt(aX * aX + aY * aY + aZ * aZ)
            val bLen = sqrt(bX * bX + bY * bY + bZ * bZ)
            if (aLen < 1e-4f || bLen < 1e-4f) return false
            val straightness = (aX * bX + aY * bY + aZ * bZ) / (aLen * bLen)
            val tipRadius = dist3(
                tip.x(), tip.y(), tip.z(), wrist.x(), wrist.y(), wrist.z(),
            )
            val pipRadius = dist3(
                pip.x(), pip.y(), pip.z(), wrist.x(), wrist.y(), wrist.z(),
            )
            return straightness <= PALM_STRAIGHT_DOT &&
                tipRadius >= pipRadius * PALM_EXTENSION_RATIO
        }

        return extended(INDEX_MCP, INDEX_PIP, INDEX_TIP) &&
            extended(MIDDLE_MCP, MIDDLE_PIP, MIDDLE_TIP) &&
            extended(RING_MCP, RING_PIP, RING_TIP) &&
            extended(PINKY_MCP, PINKY_PIP, PINKY_TIP)
    }

    private fun evaluatePalm(open: Boolean, x: Float, y: Float, ts: Long) {
        if (!open) {
            resetPalm()
            return
        }
        if (palmSinceMs < 0L) palmSinceMs = ts
        if (!palmFired && ts - palmSinceMs >= config.palm.minHoldMs) {
            palmFired = true
            callbacks.onGesture(GestureKind.OPEN_PALM_MENU, 0f, x, y, ts)
        }
    }

    private fun evaluateTwoPalm(open: Boolean, x: Float, y: Float, ts: Long) {
        if (!open) {
            resetTwoPalm()
            return
        }
        if (twoPalmSinceMs < 0L) twoPalmSinceMs = ts
        if (!twoPalmFired && ts - twoPalmSinceMs >= TWO_PALM_HOLD_MS) {
            twoPalmFired = true
            callbacks.onGesture(GestureKind.TWO_PALM_MENU, 0f, x, y, ts)
        }
    }

    /**
     * Orientation-independent fist: every long fingertip folds back to at
     * least its PIP radius from the wrist. Requiring all four fingers and a
     * timed latch keeps an ordinary pinch from toggling interaction power.
     */
    private fun isClosedFist(
        hand: List<com.google.mediapipe.tasks.components.containers.NormalizedLandmark>,
    ): Boolean {
        if (hand.size <= PINKY_TIP) return false
        val wrist = hand[WRIST]

        fun folded(mcpIndex: Int, pipIndex: Int, tipIndex: Int): Boolean {
            val mcp = hand[mcpIndex]
            val pip = hand[pipIndex]
            val tip = hand[tipIndex]
            val tipRadius = dist3(
                tip.x(), tip.y(), tip.z(), wrist.x(), wrist.y(), wrist.z(),
            )
            val pipRadius = dist3(
                pip.x(), pip.y(), pip.z(), wrist.x(), wrist.y(), wrist.z(),
            )
            val mcpRadius = dist3(
                mcp.x(), mcp.y(), mcp.z(), wrist.x(), wrist.y(), wrist.z(),
            )
            return tipRadius <= pipRadius * FIST_TIP_TO_PIP_RATIO &&
                tipRadius <= mcpRadius * FIST_TIP_TO_MCP_RATIO
        }

        return folded(INDEX_MCP, INDEX_PIP, INDEX_TIP) &&
            folded(MIDDLE_MCP, MIDDLE_PIP, MIDDLE_TIP) &&
            folded(RING_MCP, RING_PIP, RING_TIP) &&
            folded(PINKY_MCP, PINKY_PIP, PINKY_TIP)
    }

    private fun evaluateFist(closed: Boolean, x: Float, y: Float, ts: Long) {
        if (!closed) {
            resetFist()
            return
        }
        if (fistSinceMs < 0L) fistSinceMs = ts
        if (!fistFired && ts - fistSinceMs >= FIST_HOLD_MS) {
            fistFired = true
            callbacks.onGesture(GestureKind.FIST_TOGGLE, 0f, x, y, ts)
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
        // A clearly closed pinch is unambiguous enough to engage on the first
        // inference result. Near the boundary we keep the proven two-frame
        // debounce, so lowering perceived latency does not invite false clicks.
        val required = if (want) {
            if (ratio <= DEEP_ENTER_THRESHOLD) 1 else ENGAGE_FRAMES
        } else RELEASE_FRAMES
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
        resetPalm()
    }

    private fun resetPalm() {
        palmSinceMs = -1L
        palmFired = false
    }

    private fun resetTwoPalm() {
        twoPalmSinceMs = -1L
        twoPalmFired = false
    }

    private fun resetFist() {
        fistSinceMs = -1L
        fistFired = false
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
        private const val INDEX_PIP = 6
        private const val INDEX_TIP = 8
        private const val MIDDLE_MCP = 9
        private const val MIDDLE_PIP = 10
        private const val MIDDLE_TIP = 12
        private const val RING_MCP = 13
        private const val RING_PIP = 14
        private const val RING_TIP = 16
        private const val PINKY_MCP = 17
        private const val PINKY_PIP = 18
        private const val PINKY_TIP = 20
        private const val ENTER_THRESHOLD = .28f
        private const val DEEP_ENTER_THRESHOLD = .20f
        private const val DEEP_RAW_ENTER_THRESHOLD = .18f
        private const val EXIT_THRESHOLD = .38f
        private const val EMA_ALPHA = .5f
        private const val ENGAGE_FRAMES = 2
        private const val RELEASE_FRAMES = 2
        private const val PALM_STRAIGHT_DOT = -.62f
        private const val PALM_EXTENSION_RATIO = 1.08f
        private const val FIST_TIP_TO_PIP_RATIO = 1.08f
        private const val FIST_TIP_TO_MCP_RATIO = 1.22f
        private const val FIST_HOLD_MS = 400L
        private const val TWO_PALM_HOLD_MS = 550L
        private const val MAX_ATELIER_FPS = 25f
    }
}
