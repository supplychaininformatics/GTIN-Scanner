package com.sanford.gtinscanner.app

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.Build
import android.os.Bundle

/**
 * Zebra DataWedge integration. DataWedge decodes the barcode and hands it to
 * this app as an Android broadcast — no keyboard emulation, so the scan
 * arrives as one string (GS1 group separators intact) instead of keystrokes.
 *
 * [configure] creates/updates a DataWedge profile bound to this app that
 * enables the scanner and sets intent output to [ACTION]. It is idempotent, so
 * it is safe to call on every launch; it can be replaced by an MDM-pushed
 * profile without code changes as long as the action and extra match.
 */
object DataWedge {
    const val ACTION = "com.sanford.gtinscanner.SCAN"
    private const val EXTRA_DATA = "com.symbol.datawedge.data_string"
    private const val PROFILE = "GtinScanner"

    fun configure(context: Context) {
        val barcode = Bundle().apply {
            putString("PLUGIN_NAME", "BARCODE")
            putString("RESET_CONFIG", "true")
            putBundle(
                "PARAM_LIST",
                Bundle().apply {
                    putString("scanner_selection", "auto")
                    putString("scanner_input_enabled", "true")
                },
            )
        }
        val intentOutput = Bundle().apply {
            putString("PLUGIN_NAME", "INTENT")
            putString("RESET_CONFIG", "true")
            putBundle(
                "PARAM_LIST",
                Bundle().apply {
                    putString("intent_output_enabled", "true")
                    putString("intent_action", ACTION)
                    putString("intent_category", "android.intent.category.DEFAULT")
                    putString("intent_delivery", "2") // 2 = broadcast
                },
            )
        }
        val app = Bundle().apply {
            putString("PACKAGE_NAME", context.packageName)
            putStringArray("ACTIVITY_LIST", arrayOf("*"))
        }
        val profile = Bundle().apply {
            putString("PROFILE_NAME", PROFILE)
            putString("PROFILE_ENABLED", "true")
            putString("CONFIG_MODE", "CREATE_IF_NOT_EXIST")
            putParcelableArray("PLUGIN_CONFIG", arrayOf(barcode, intentOutput))
            putParcelableArray("APP_LIST", arrayOf(app))
        }
        context.sendBroadcast(
            Intent("com.symbol.datawedge.api.ACTION").putExtra("com.symbol.datawedge.api.SET_CONFIG", profile),
        )
    }

    /**
     * Register while the activity is in the foreground. The receiver must be
     * exported because DataWedge is another app, so any app could forge this
     * broadcast; that is acceptable because a scan is untrusted input anyway
     * and is validated before it is queued and again by the server.
     */
    fun register(context: Context, onScan: (String) -> Unit): BroadcastReceiver {
        val receiver = object : BroadcastReceiver() {
            override fun onReceive(ctx: Context, intent: Intent) {
                intent.getStringExtra(EXTRA_DATA)?.let(onScan)
            }
        }
        val filter = IntentFilter(ACTION).apply { addCategory(Intent.CATEGORY_DEFAULT) }
        if (Build.VERSION.SDK_INT >= 33) {
            context.registerReceiver(receiver, filter, Context.RECEIVER_EXPORTED)
        } else {
            context.registerReceiver(receiver, filter)
        }
        return receiver
    }
}
