package com.mlomega.xr.reflexvision

import android.content.Context
import android.graphics.Bitmap
import com.google.mlkit.vision.common.InputImage
import com.google.mlkit.vision.label.ImageLabeling
import com.google.mlkit.vision.label.defaults.ImageLabelerOptions
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.atomic.AtomicBoolean

/**
 * Low-cost semantic tier for Augmented Reality object cards.
 *
 * This is not a VLM and never pretends to identify an exact product. It returns
 * at most [maxLabels] generic labels from the bundled ML Kit model. The PC's
 * already-hot VisionRT detector remains authoritative for localisation; these
 * labels are a fast semantic cross-check/fallback. Precise product/manual work
 * remains an explicit user action outside this hot path.
 *
 * Backpressure is keep-only-latest: while ML Kit is busy every new frame is
 * dropped. The C# bridge also throttles before the GPU readback.
 */
class InstantImageLabeler(
    appContext: Context,
    private val callbacks: InstantImageLabelCallbacks,
    minimumConfidence: Float = 0.65f,
    private val maxLabels: Int = 3,
) {
    private val busy = AtomicBoolean(false)
    private val closed = AtomicBoolean(false)
    private val labeler = ImageLabeling.getClient(
        ImageLabelerOptions.Builder()
            .setConfidenceThreshold(minimumConfidence.coerceIn(0.0f, 1.0f))
            .build()
    )

    /** Returns false when closed or a previous request is still running. */
    fun pushFrame(bitmap: Bitmap?, rotationDegrees: Int, timestampMs: Long): Boolean {
        if (bitmap == null || closed.get() || !busy.compareAndSet(false, true)) return false
        val rotation = when (((rotationDegrees % 360) + 360) % 360) {
            90 -> 90
            180 -> 180
            270 -> 270
            else -> 0
        }
        try {
            labeler.process(InputImage.fromBitmap(bitmap, rotation))
                .addOnSuccessListener { labels ->
                    val out = JSONArray()
                    labels.sortedByDescending { it.confidence }
                        .take(maxLabels.coerceIn(1, 5))
                        .forEach { label ->
                            out.put(
                                JSONObject()
                                    .put("label", label.text)
                                    .put("confidence", label.confidence.toDouble())
                                    .put("index", label.index)
                            )
                        }
                    callbacks.onLabels(out.toString(), timestampMs)
                }
                .addOnFailureListener { error ->
                    callbacks.onError(
                        "mlkit image label: ${error.message ?: error.javaClass.simpleName}"
                    )
                }
                .addOnCompleteListener { busy.set(false) }
            return true
        } catch (error: Throwable) {
            busy.set(false)
            callbacks.onError(
                "mlkit image label submit: ${error.message ?: error.javaClass.simpleName}"
            )
            return false
        }
    }

    fun close() {
        if (!closed.compareAndSet(false, true)) return
        labeler.close()
        busy.set(false)
    }
}
