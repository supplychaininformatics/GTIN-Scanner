package com.sanford.gtinscanner.core

import java.io.IOException
import org.json.JSONArray
import org.json.JSONObject

enum class SyncStatus {
    /** Queue is empty. */
    DRAINED,
    /** Some operations were told to retry; they are still queued. */
    PARTIAL,
    /** Could not reach the server; nothing changed. */
    OFFLINE,
    /** Token refused — needs re-provisioning; nothing changed. */
    AUTH_FAILED,
    RATE_LIMITED,
    /** Server-side failure (5xx/503); nothing in the batch was processed. */
    SERVER_ERROR,
    /** The response didn't match the request (or we sent a request the server
     *  calls malformed). A client bug: nothing was removed from the queue. */
    PROTOCOL_ERROR,
}

data class Rejection(val opId: String, val code: String)

data class SyncReport(
    val status: SyncStatus,
    val applied: Int,
    val duplicates: Int,
    val rejected: List<Rejection>,
    val remaining: Int,
    val retryAfterSeconds: Int? = null,
)

/**
 * Uploads the queue to POST /v1/sync.
 *
 * An operation leaves the queue only when the server says it is finished with
 * it: applied, duplicate (an earlier attempt already landed) or rejected (it
 * can never succeed, so keeping it would only block the queue). `retry` and
 * every failure to get an answer leave it queued. Ops are resent with the same
 * op_id, which is what lets the server count a scan exactly once.
 */
class SyncEngine(
    private val transport: Transport,
    private val queue: OpQueue,
    private val batchSize: Int = 100,
) {
    fun syncOnce(): SyncReport {
        var applied = 0
        var duplicates = 0
        val rejected = mutableListOf<Rejection>()

        fun report(status: SyncStatus, retryAfter: Int? = null) =
            SyncReport(status, applied, duplicates, rejected.toList(), queue.size(), retryAfter)

        while (true) {
            val batch = queue.peek(batchSize)
            if (batch.isEmpty()) return report(SyncStatus.DRAINED)

            val body = JSONObject()
                .put("ops", JSONArray(batch.map { JSONObject(it.payload) }))
                .toString()
            val response = try {
                transport.postJson("/v1/sync", body)
            } catch (e: IOException) {
                return report(SyncStatus.OFFLINE)
            }
            when (response.status) {
                200 -> Unit
                401 -> return report(SyncStatus.AUTH_FAILED)
                429 -> return report(SyncStatus.RATE_LIMITED, response.retryAfterSeconds)
                400, 413 -> return report(SyncStatus.PROTOCOL_ERROR)
                else -> return report(SyncStatus.SERVER_ERROR)
            }

            val results = try {
                JSONObject(response.body).getJSONArray("results")
            } catch (e: Exception) {
                return report(SyncStatus.PROTOCOL_ERROR)
            }
            if (results.length() != batch.size) return report(SyncStatus.PROTOCOL_ERROR)

            val finished = mutableListOf<Long>()
            var anyRetry = false
            for ((i, op) in batch.withIndex()) {
                val result = results.getJSONObject(i)
                if (result.optString("op_id") != op.opId) return report(SyncStatus.PROTOCOL_ERROR)
                when (result.optString("status")) {
                    "applied" -> { applied++; finished += op.seq }
                    "duplicate" -> { duplicates++; finished += op.seq }
                    "rejected" -> {
                        rejected += Rejection(op.opId, result.optString("code", "unknown"))
                        finished += op.seq
                    }
                    else -> anyRetry = true // "retry", or a status this client doesn't know
                }
            }
            queue.remove(finished)
            if (anyRetry) return report(SyncStatus.PARTIAL)
        }
    }
}
