package com.mlomega.xr.livetransport

import android.Manifest
import android.bluetooth.BluetoothAdapter
import android.bluetooth.le.ScanCallback
import android.bluetooth.le.ScanResult
import android.bluetooth.le.ScanSettings
import android.content.Context
import android.content.pm.PackageManager
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import android.net.wifi.WifiManager
import android.os.Build
import androidx.annotation.Keep
import org.json.JSONArray
import org.json.JSONObject
import java.security.MessageDigest
import java.util.concurrent.ConcurrentHashMap
import kotlin.math.sqrt

/**
 * Bounded radio/magnetic fingerprint sampler for live indoor mapping.
 *
 * Unity owns geometry through the tracked XREAL head pose.  This class contributes
 * only radio and magnetic fingerprints: it never claims a position by itself and
 * never sends identifiers over the network. BSSIDs/BLE addresses are salted and
 * hashed before crossing JNI.
 */
@Keep
class IndoorFingerprintBridge(private val appContext: Context) : SensorEventListener {
    private val context = appContext.applicationContext
    private val wifi = context.getSystemService(Context.WIFI_SERVICE) as? WifiManager
    private val sensors = context.getSystemService(Context.SENSOR_SERVICE) as? SensorManager
    private val magnetometer = sensors?.getDefaultSensor(Sensor.TYPE_MAGNETIC_FIELD)
    private val bleSamples = ConcurrentHashMap<String, Int>()
    private val salt = context.packageName + ":mlomega-indoor-v1"

    @Volatile private var magneticX = Float.NaN
    @Volatile private var magneticY = Float.NaN
    @Volatile private var magneticZ = Float.NaN
    @Volatile private var running = false
    private var scanner: android.bluetooth.le.BluetoothLeScanner? = null

    private val scanCallback = object : ScanCallback() {
        override fun onScanResult(callbackType: Int, result: ScanResult?) {
            val address = result?.device?.address ?: return
            bleSamples[hashId("ble", address)] = result.rssi
            trimBle()
        }

        override fun onBatchScanResults(results: MutableList<ScanResult>?) {
            results.orEmpty().forEach { onScanResult(0, it) }
        }
    }

    @Keep
    fun start(): Boolean {
        if (running) return true
        running = true
        magnetometer?.let {
            sensors?.registerListener(this, it, SensorManager.SENSOR_DELAY_NORMAL)
        }
        startBleIfPermitted()
        return true
    }

    @Keep
    fun stop() {
        running = false
        sensors?.unregisterListener(this)
        try {
            scanner?.stopScan(scanCallback)
        } catch (_: SecurityException) {
            // Permission may have been revoked while active; stopping remains safe.
        }
        scanner = null
        bleSamples.clear()
    }

    @Keep
    fun snapshotJson(): String {
        if (!running) start()
        val root = JSONObject()
        root.put("schema_version", 1)
        root.put("captured_at_unix_ms", System.currentTimeMillis())

        val wifiArray = JSONArray()
        if (hasLocationPermission()) {
            try {
                @Suppress("DEPRECATION")
                wifi?.startScan()
                val rows = wifi?.scanResults.orEmpty()
                    .filter { !it.BSSID.isNullOrBlank() }
                    .sortedByDescending { it.level }
                    .take(MAX_RADIOS)
                rows.forEach { row ->
                    wifiArray.put(
                        JSONObject()
                            .put("id", hashId("wifi", row.BSSID))
                            .put("rssi", row.level.coerceIn(-127, 0))
                            .put("frequency_mhz", row.frequency)
                    )
                }
            } catch (_: SecurityException) {
                // Empty array is an explicit unavailable signal to the map builder.
            }
        }
        root.put("wifi", wifiArray)

        val bleArray = JSONArray()
        bleSamples.entries
            .sortedByDescending { it.value }
            .take(MAX_RADIOS)
            .forEach { (id, rssi) ->
                bleArray.put(
                    JSONObject()
                        .put("id", id)
                        .put("rssi", rssi.coerceIn(-127, 0))
                )
            }
        root.put("ble", bleArray)

        val magnetic = JSONObject()
        if (magneticX.isFinite() && magneticY.isFinite() && magneticZ.isFinite()) {
            val magnitude = sqrt(
                magneticX * magneticX +
                    magneticY * magneticY +
                    magneticZ * magneticZ
            )
            magnetic
                .put("x_ut", magneticX.toDouble())
                .put("y_ut", magneticY.toDouble())
                .put("z_ut", magneticZ.toDouble())
                .put("magnitude_ut", magnitude.toDouble())
        }
        root.put("magnetic", magnetic)
        root.put(
            "radio_permission",
            hasBluetoothPermission() && hasLocationPermission()
        )
        return root.toString()
    }

    override fun onSensorChanged(event: SensorEvent?) {
        val values = event?.values ?: return
        if (event.sensor.type != Sensor.TYPE_MAGNETIC_FIELD || values.size < 3) return
        magneticX = values[0]
        magneticY = values[1]
        magneticZ = values[2]
    }

    override fun onAccuracyChanged(sensor: Sensor?, accuracy: Int) = Unit

    private fun startBleIfPermitted() {
        if (!hasBluetoothPermission()) return
        try {
            scanner = BluetoothAdapter.getDefaultAdapter()?.bluetoothLeScanner
            val settings = ScanSettings.Builder()
                .setScanMode(ScanSettings.SCAN_MODE_LOW_POWER)
                .build()
            scanner?.startScan(null, settings, scanCallback)
        } catch (_: SecurityException) {
            scanner = null
        }
    }

    private fun hasBluetoothPermission(): Boolean =
        Build.VERSION.SDK_INT < Build.VERSION_CODES.S ||
            context.checkSelfPermission(Manifest.permission.BLUETOOTH_SCAN) ==
            PackageManager.PERMISSION_GRANTED

    private fun hasLocationPermission(): Boolean =
        context.checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) ==
            PackageManager.PERMISSION_GRANTED

    private fun hashId(kind: String, raw: String): String {
        val digest = MessageDigest.getInstance("SHA-256")
            .digest("$salt|$kind|${raw.lowercase()}".toByteArray(Charsets.UTF_8))
        return digest.take(10).joinToString("") { "%02x".format(it) }
    }

    private fun trimBle() {
        if (bleSamples.size <= MAX_RADIOS * 2) return
        bleSamples.entries
            .sortedBy { it.value }
            .take(bleSamples.size - MAX_RADIOS)
            .forEach { bleSamples.remove(it.key) }
    }

    companion object {
        private const val MAX_RADIOS = 16
    }
}
