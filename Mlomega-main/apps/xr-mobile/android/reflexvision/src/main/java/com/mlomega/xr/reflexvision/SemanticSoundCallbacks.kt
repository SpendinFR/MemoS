package com.mlomega.xr.reflexvision

/** JNI-safe callbacks for the opt-in YAMNet semantic sound classifier. */
interface SemanticSoundCallbacks {
    fun onSound(label: String, score: Float, timestampMs: Long)
    fun onError(message: String)
}
