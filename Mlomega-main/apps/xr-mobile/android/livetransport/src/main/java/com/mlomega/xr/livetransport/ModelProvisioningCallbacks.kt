package com.mlomega.xr.livetransport

/**
 * MLOmega V19 — E48-A. Provisioning progress from [ModelProvisioner] into the
 * host (Unity via `AndroidJavaProxy`, or a JVM test double).
 *
 * Same JNI-friendly shape as [LiveTransportCallbacks]: all methods are invoked on
 * a background thread; the C# bridge marshals them onto the Unity main thread to
 * drive a discreet progress card. Byte counts are plain `long`s so a >2 GB total
 * (never actually reached — the ASR archives are ~300-400 MB) is still safe.
 */
interface ModelProvisioningCallbacks {

    /**
     * The manifest was read: [total] device models advertised, [missing] of which
     * need downloading. When missing == 0 the phone is already fully provisioned
     * and no further callbacks (other than [onProvisioningComplete]) fire.
     */
    fun onProvisioningPlan(total: Int, missing: Int)

    /**
     * Download progress for one model. [receivedBytes] of [totalBytes]; totalBytes
     * is -1 when the server did not send a content length. Throttled to ~1 % steps.
     */
    fun onModelProgress(name: String, receivedBytes: Long, totalBytes: Long)

    /**
     * One model finished downloading, verified (sha256) and installed (extracted if
     * an archive). Its feature can be (re)armed on the next activation / launch.
     */
    fun onModelReady(name: String)

    /**
     * A non-fatal provisioning error. The named model stays absent and its feature
     * stays in honest degraded mode; the rest of the run continues. [name] is
     * `__manifest__` when the manifest fetch itself failed.
     */
    fun onProvisioningError(name: String, message: String)

    /** The whole provisioning pass finished (with or without per-model errors). */
    fun onProvisioningComplete()
}
