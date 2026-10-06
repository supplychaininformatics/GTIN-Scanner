package com.sanford.gtinscanner.core

/** One contract line as served by GET /v1/reference/contract-lines. */
data class ReferenceRow(
    val gtin: String,
    val item: String,
    val company: String,
    val brand: String,
    val description: String,
    val gtinUom: String,
    val uou: String,
    val lawsonId: String,
    val lawsonUom: String,
    val onHold: Boolean,
)

/** An operation waiting to be uploaded. [payload] is the exact wire JSON. */
data class QueuedOp(val seq: Long, val opId: String, val payload: String)

/**
 * A mirror download in progress. [after] is the cursor of the last page stored;
 * [complete] means every page arrived and only the commit is outstanding.
 */
data class StagingState(val version: String, val after: String?, val complete: Boolean)

/** What the handheld knows about one GTIN in one session. */
data class LogEntry(
    val gtin: String,
    val rawScan: String,
    val firstScannedAt: String,
    val lastScannedAt: String,
    val count: Int,
    val row: ReferenceRow?,
)
