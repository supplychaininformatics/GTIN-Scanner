package com.sanford.gtinscanner.core

import java.io.IOException
import org.json.JSONArray
import org.json.JSONObject

class InMemoryOpQueue : OpQueue {
    private var nextSeq = 1L
    val ops = mutableListOf<QueuedOp>()

    override fun enqueue(opId: String, payload: String) {
        ops += QueuedOp(nextSeq++, opId, payload)
    }

    override fun peek(limit: Int) = ops.take(limit)

    override fun remove(seqs: Collection<Long>) {
        ops.removeAll { it.seq in seqs }
    }

    override fun size() = ops.size

    fun payloads() = ops.map { JSONObject(it.payload) }
}

class InMemoryReferenceStore : ReferenceStore {
    private var committedVersion: String? = null
    private var committed = mapOf<String, ReferenceRow>()
    private var staging: StagingState? = null
    private var staged = mutableMapOf<String, ReferenceRow>()

    override fun version() = committedVersion
    override fun lookup(gtin: String) = committed[gtin]
    override fun stagingState() = staging

    override fun startStaging(version: String) {
        staged = mutableMapOf()
        staging = StagingState(version, null, false)
    }

    override fun appendStaged(rows: List<ReferenceRow>, next: String?) {
        rows.forEach { staged[it.gtin] = it }
        staging = staging!!.copy(after = next ?: staging!!.after, complete = next == null)
    }

    override fun commitStaging() {
        committed = staged.toMap()
        committedVersion = staging!!.version
        staging = null
        staged = mutableMapOf()
    }

    override fun discardStaging() {
        staging = null
        staged = mutableMapOf()
    }

    fun size() = committed.size

    fun anyRow(): ReferenceRow = committed.values.first()
}

class InMemorySessionLog : SessionLog {
    private val entries = linkedMapOf<Pair<String, String>, LogEntry>()

    override fun recordScan(
        sessionId: String,
        gtin: String,
        rawScan: String,
        at: String,
        row: ReferenceRow?,
    ): LogEntry {
        val key = sessionId to gtin
        val updated = entries[key]?.copy(lastScannedAt = at, count = entries[key]!!.count + 1)
            ?: LogEntry(gtin, rawScan, at, at, 1, row)
        entries[key] = updated
        return updated
    }

    override fun entries(sessionId: String) = entries.filterKeys { it.first == sessionId }.values.toList()
}

/** Transport whose responses are scripted per call; a thrown IOException models a dropped connection. */
class ScriptedTransport(private val handler: (method: String, path: String, query: Map<String, String>, body: String?) -> HttpResult) : Transport {
    val calls = mutableListOf<Triple<String, String, Map<String, String>>>()

    override fun get(path: String, query: Map<String, String>): HttpResult {
        calls += Triple("GET", path, query)
        return handler("GET", path, query, null)
    }

    override fun postJson(path: String, body: String): HttpResult {
        calls += Triple("POST", path, emptyMap())
        return handler("POST", path, emptyMap(), body)
    }
}

fun ok(json: JSONObject) = HttpResult(200, json.toString())
fun offline(): Nothing = throw IOException("no route to host")

fun rowJson(gtin: String, item: String = "I$gtin") = JSONObject()
    .put("gtin", gtin).put("item", item).put("company", "ACME").put("brand", "B")
    .put("description", "Widget").put("gtin_uom", "BX").put("uou", "-")
    .put("lawson_id", "L1").put("lawson_uom", "EA").put("on_hold", false)

fun rowsPage(gtins: List<String>, next: String?, version: String = "v1") = ok(
    JSONObject().put("version", version).put("rows", JSONArray(gtins.map { rowJson(it) }))
        .put("next", next ?: JSONObject.NULL),
)

fun versionResponse(version: String) = ok(JSONObject().put("version", version).put("row_count", 0))

fun ref(gtin: String) = ReferenceRow(gtin, "I", "ACME", "B", "Widget", "BX", "-", "L1", "EA", false)
