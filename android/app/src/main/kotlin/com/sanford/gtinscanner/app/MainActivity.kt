package com.sanford.gtinscanner.app

import android.app.Activity
import android.content.BroadcastReceiver
import android.content.Context
import android.graphics.Color
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.text.InputType
import android.view.View
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import com.sanford.gtinscanner.core.ScanController
import com.sanford.gtinscanner.core.ScanResult

/**
 * Deliberately plain, programmatic UI: this is the offline-first scan loop
 * (start session → scan → end session), not a design. Everything it shows
 * comes from local storage, so it behaves the same with or without a network.
 */
class MainActivity : Activity() {
    private lateinit var app: GtinScannerApp
    private lateinit var controller: ScanController
    private lateinit var status: TextView
    private lateinit var body: LinearLayout
    private lateinit var lastResult: TextView
    private lateinit var history: TextView
    private var receiver: BroadcastReceiver? = null
    private val ui = Handler(Looper.getMainLooper())
    private val tick = object : Runnable {
        override fun run() {
            renderStatus()
            ui.postDelayed(this, 3000)
        }
    }

    private var sessionId: String?
        get() = getSharedPreferences("session", Context.MODE_PRIVATE).getString("active", null)
        set(value) = getSharedPreferences("session", Context.MODE_PRIVATE).edit().putString("active", value).apply()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        app = application as GtinScannerApp
        controller = app.scanController

        // Debug builds: `adb shell am start -n <pkg>/.MainActivity --es sync_url http://10.0.2.2:8080 --es sync_token dev-token`
        val url = intent.getStringExtra("sync_url")
        val token = intent.getStringExtra("sync_token")
        if (url != null && token != null) ConfigSource.saveDebug(this, url, token)

        val root = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(24, 24, 24, 24) }
        status = TextView(this).apply { textSize = 14f }
        body = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        root.addView(status)
        root.addView(body)
        setContentView(ScrollView(this).apply { addView(root) })

        lastResult = TextView(this).apply { textSize = 18f; setPadding(0, 24, 0, 24) }
        history = TextView(this).apply { textSize = 14f }
        DataWedge.configure(this)
    }

    override fun onResume() {
        super.onResume()
        receiver = DataWedge.register(this, ::onScanned)
        ui.post(tick)
        render()
    }

    override fun onPause() {
        receiver?.let(::unregisterReceiver)
        receiver = null
        ui.removeCallbacks(tick)
        super.onPause()
    }

    private fun render() {
        body.removeAllViews()
        val sid = sessionId
        if (sid == null) renderStartForm() else renderSession(sid)
        renderStatus()
    }

    private fun renderStartForm() {
        val sanfordId = EditText(this).apply { hint = "Sanford ID"; inputType = InputType.TYPE_CLASS_TEXT }
        val location = EditText(this).apply { hint = "Warehouse location"; inputType = InputType.TYPE_CLASS_TEXT }
        val error = TextView(this).apply { setTextColor(Color.RED) }
        val start = Button(this).apply {
            text = "Start session"
            setOnClickListener {
                try {
                    sessionId = controller.startSession(sanfordId.text.toString(), location.text.toString())
                    SyncScheduler.kick(this@MainActivity)
                    render()
                } catch (e: IllegalArgumentException) {
                    error.text = e.message
                }
            }
        }
        listOf<View>(sanfordId, location, error, start).forEach(body::addView)
    }

    private fun renderSession(sid: String) {
        val end = Button(this).apply {
            text = "End session"
            setOnClickListener {
                controller.endSession(sid)
                sessionId = null
                SyncScheduler.kick(this@MainActivity)
                render()
            }
        }
        lastResult.text = "Scan an item"
        listOf<View>(lastResult, end, history).forEach(body::addView)
        renderHistory(sid)
    }

    private fun onScanned(raw: String) {
        val sid = sessionId ?: return
        when (val result = controller.onScan(sid, raw)) {
            is ScanResult.Invalid -> lastResult.text = result.reason
            is ScanResult.Scanned -> {
                val row = result.row
                lastResult.text = buildString {
                    append(if (result.duplicate) "DUPLICATE x${result.scanCount}  " else "")
                    if (row == null) {
                        append("${result.gtin}\nNot on contract file — will be verified when online")
                    } else {
                        append(if (row.onHold) "ON HOLD  " else "")
                        append("${row.item}\n${row.company}\n${row.description}")
                    }
                }
            }
        }
        renderHistory(sid)
        renderStatus()
        SyncScheduler.kick(this)
    }

    private fun renderHistory(sid: String) {
        history.text = app.database.sessionLog.entries(sid).asReversed().joinToString("\n") {
            "${it.row?.item ?: it.gtin}  x${it.count}"
        }
    }

    private fun renderStatus() {
        val pending = app.database.opQueue.size()
        val mirror = app.database.reference.version()?.let { "mirror ${it.take(8)}" } ?: "no mirror yet"
        val configured = if (ConfigSource.load(this) == null) "  |  NOT PROVISIONED" else ""
        status.text = "$pending waiting to sync  |  $mirror$configured"
    }
}
