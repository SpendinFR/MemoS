package com.mlomega.xr.reflexvision

/** JNI-friendly callbacks for the opt-in bundled ML Kit image labeler. */
interface InstantImageLabelCallbacks {
    fun onLabels(labelsJson: String, timestampMs: Long)
    fun onError(message: String)
}
