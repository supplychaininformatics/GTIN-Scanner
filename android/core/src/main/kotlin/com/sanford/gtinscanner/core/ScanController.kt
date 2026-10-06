package com.sanford.gtinscanner.core

import java.time.Instant
import java.time.temporal.ChronoUnit
import java.util.UUID
import org.json.JSONObject

sealed interface ScanResult {
    /**
     * [row] is the contract line from the on-device mirror, or null when the
     * code isn't in it. Null is provisional, not a final Not Found: the server
     * re-resolves every scan at sync time (including goodID), so the UI should
     * say "not on contract file — will be verified when online".
     */
    data class Scanned(
        val gtin: String,
        val row: ReferenceRow?,
        val duplicate: Boolean,
        val scanCount: Int,
    ) : ScanResult

    /** Refused before anything was recorded; nothing was queued. */
    data class Invalid(val reason: String) : ScanResult
}

/**
 * The offline-first scan flow: resolve against the mirror, keep the on-screen
 * history, and queue the raw facts for the server. Nothing here needs a
 * network, and everything queued is what /v1/sync expects (see SYNC-API.md).
 */
class ScanController(
    private val queue: OpQueue,
    private val reference: ReferenceStore,
    private val log: SessionLog,
    private val clock: () -> Instant = Instant::now,
    private val newId: () -> String = { UUID.randomUUID().toString() },
) {
    fun startSession(sanfordId: String, location: String): String {
        val id = requireText(sanfordId, MAX_SANFORD_ID, "Sanford ID")
        val loc = requireText(location, MAX_LOCATION, "location")
        val sessionId = newId()
        enqueue(
            JSONObject()
                .put("type", "create_session")
                .put("session_id", sessionId)
                .put("sanford_id", id)
                .put("location", loc)
                .put("created_at", now()),
        )
        return sessionId
    }

    fun onScan(sessionId: String, rawScan: String): ScanResult {
        val raw = rawScan.trim()
        if (raw.isEmpty() || raw.length > MAX_RAW_SCAN) return ScanResult.Invalid("Unreadable barcode")
        if (raw.any { (it.code < 0x20 || it.code == 0x7F) && it != GS }) {
            return ScanResult.Invalid("Unreadable barcode")
        }
        val gtin = Gs1.extractGtin(raw)
        if (gtin.length > MAX_GTIN) return ScanResult.Invalid("Unreadable barcode")

        val at = now()
        // Queue first: if the process dies right after, the scan is not lost.
        enqueue(
            JSONObject()
                .put("type", "scan")
                .put("session_id", sessionId)
                .put("raw_scan", raw)
                .put("scanned_at", at),
        )
        val row = reference.lookup(gtin)
        val entry = log.recordScan(sessionId, gtin, raw, at, row)
        return ScanResult.Scanned(gtin, row, duplicate = entry.count > 1, scanCount = entry.count)
    }

    fun endSession(sessionId: String) {
        enqueue(
            JSONObject()
                .put("type", "end_session")
                .put("session_id", sessionId)
                .put("ended_at", now()),
        )
    }

    private fun enqueue(op: JSONObject) {
        val opId = newId()
        op.put("op_id", opId)
        queue.enqueue(opId, op.toString())
    }

    private fun now(): String = clock().truncatedTo(ChronoUnit.SECONDS).toString()

    private fun requireText(value: String, max: Int, label: String): String {
        val v = value.trim()
        require(v.isNotEmpty() && v.length <= max && v.none { it.code < 0x20 || it.code == 0x7F }) {
            "Invalid $label"
        }
        return v
    }

    private companion object {
        const val GS = '\u001d'
        const val MAX_SANFORD_ID = 64
        const val MAX_LOCATION = 128
        const val MAX_RAW_SCAN = 256
        const val MAX_GTIN = 64
    }
}
