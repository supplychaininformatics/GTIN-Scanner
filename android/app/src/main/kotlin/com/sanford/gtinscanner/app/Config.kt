package com.sanford.gtinscanner.app

import android.content.Context
import android.content.RestrictionsManager
import android.content.pm.ApplicationInfo

data class SyncConfig(val syncUrl: String, val token: String, val allowCleartext: Boolean)

/**
 * Where this handheld learns which server to talk to and how to authenticate.
 *
 * Production: Managed Configuration pushed by the MDM (keys `sync_url`,
 * `sync_token`) — nothing to type on the device and nothing in the APK.
 * Debug builds only: values passed on launch (see MainActivity) and kept in
 * app-private storage, so the emulator can be pointed at the dev server.
 */
object ConfigSource {
    private const val PREFS = "debug_config"

    fun load(context: Context): SyncConfig? {
        val managed = context.getSystemService(Context.RESTRICTIONS_SERVICE) as RestrictionsManager
        val restrictions = managed.applicationRestrictions
        val url = restrictions.getString("sync_url").orEmpty().trim()
        val token = restrictions.getString("sync_token").orEmpty().trim()
        if (url.isNotEmpty() && token.isNotEmpty()) return SyncConfig(url, token, allowCleartext = false)

        if (isDebuggable(context)) {
            val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            val dUrl = prefs.getString("sync_url", null)
            val dToken = prefs.getString("sync_token", null)
            if (!dUrl.isNullOrBlank() && !dToken.isNullOrBlank()) {
                return SyncConfig(dUrl, dToken, allowCleartext = true)
            }
        }
        return null
    }

    fun saveDebug(context: Context, url: String, token: String) {
        if (!isDebuggable(context)) return
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit()
            .putString("sync_url", url).putString("sync_token", token).apply()
    }

    private fun isDebuggable(context: Context) =
        context.applicationInfo.flags and ApplicationInfo.FLAG_DEBUGGABLE != 0
}
