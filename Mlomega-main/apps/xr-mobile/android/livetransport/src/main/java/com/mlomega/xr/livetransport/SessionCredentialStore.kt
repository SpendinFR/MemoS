package com.mlomega.xr.livetransport

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import org.json.JSONObject
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/** Android-only durable session credentials for crash/network resumption.
 *
 * The token is encrypted with a non-exportable Android Keystore AES key.  It is
 * deliberately cleared only after explicit CloseDay completion (or an invalid
 * renew response), never on Activity/Unity lifecycle loss.
 */
object SessionCredentialStore {
    private const val KEY_ALIAS = "mlomega_phoneonly_session_v1"
    private const val PREFS = "mlomega_phoneonly_session"
    private const val VALUE = "encrypted_credentials"

    @JvmStatic
    fun save(context: Context, sessionId: String, token: String) {
        require(sessionId.isNotBlank() && token.isNotBlank())
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, key())
        val plain = JSONObject().put("session_id", sessionId).put("token", token)
            .toString().toByteArray(Charsets.UTF_8)
        val payload = JSONObject()
            .put("iv", Base64.encodeToString(cipher.iv, Base64.NO_WRAP))
            .put("ciphertext", Base64.encodeToString(cipher.doFinal(plain), Base64.NO_WRAP))
            .toString()
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().putString(VALUE, payload).apply()
    }

    /** Returns a compact JSON object for Unity, or null when absent/invalid. */
    @JvmStatic
    fun load(context: Context): String? {
        return try {
            val encoded = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getString(VALUE, null)
                ?: return null
            val payload = JSONObject(encoded)
            val cipher = Cipher.getInstance("AES/GCM/NoPadding")
            cipher.init(
                Cipher.DECRYPT_MODE,
                key(),
                GCMParameterSpec(128, Base64.decode(payload.getString("iv"), Base64.NO_WRAP)),
            )
            JSONObject(String(cipher.doFinal(Base64.decode(payload.getString("ciphertext"), Base64.NO_WRAP)), Charsets.UTF_8))
                .toString()
        } catch (_: Exception) {
            clear(context)
            null
        }
    }

    @JvmStatic
    fun clear(context: Context) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().remove(VALUE).apply()
    }

    private fun key(): SecretKey {
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (store.getKey(KEY_ALIAS, null) as? SecretKey)?.let { return it }
        val generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
        generator.init(
            KeyGenParameterSpec.Builder(
                KEY_ALIAS,
                KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT,
            ).setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .build(),
        )
        return generator.generateKey()
    }
}
