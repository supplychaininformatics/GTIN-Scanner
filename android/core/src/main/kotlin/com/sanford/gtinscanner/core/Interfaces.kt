package com.sanford.gtinscanner.core

import java.io.IOException

/**
 * Durable FIFO of operations awaiting upload. Implementations must survive a
 * process kill and a battery pull: an acknowledged scan may never be lost.
 */
interface OpQueue {
    fun enqueue(opId: String, payload: String)

    /** Oldest [limit] operations, in the order they were enqueued. */
    fun peek(limit: Int): List<QueuedOp>

    fun remove(seqs: Collection<Long>)

    fun size(): Int
}

/**
 * The on-device copy of the contract lines. The mirror being read by scans is
 * never modified in place: a new version is downloaded into a staging area and
 * swapped in atomically by [commitStaging].
 */
interface ReferenceStore {
    /** Version of the committed mirror, or null if none has been downloaded. */
    fun version(): String?

    /** Exact-match lookup by GTIN string. */
    fun lookup(gtin: String): ReferenceRow?

    fun stagingState(): StagingState?

    /** Begin (or restart) a download of [version], discarding any earlier staging. */
    fun startStaging(version: String)

    /** Store a page and its continuation cursor together, atomically. */
    fun appendStaged(rows: List<ReferenceRow>, next: String?)

    /** Atomically replace the mirror with the staged copy. */
    fun commitStaging()

    fun discardStaging()
}

/** Per-session scan history, for duplicate detection and the on-screen list. */
interface SessionLog {
    /** Upsert: first scan of [gtin] in the session creates the entry, later ones bump it. */
    fun recordScan(sessionId: String, gtin: String, rawScan: String, at: String, row: ReferenceRow?): LogEntry

    fun entries(sessionId: String): List<LogEntry>
}

data class HttpResult(val status: Int, val body: String, val retryAfterSeconds: Int? = null)

/** Implementations signal "could not reach the server" by throwing [IOException]. */
interface Transport {
    @Throws(IOException::class)
    fun get(path: String, query: Map<String, String> = emptyMap()): HttpResult

    @Throws(IOException::class)
    fun postJson(path: String, body: String): HttpResult
}
