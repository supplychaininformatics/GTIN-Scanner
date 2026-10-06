package com.sanford.gtinscanner.app

import android.content.ContentValues
import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper
import com.sanford.gtinscanner.core.LogEntry
import com.sanford.gtinscanner.core.OpQueue
import com.sanford.gtinscanner.core.QueuedOp
import com.sanford.gtinscanner.core.ReferenceRow
import com.sanford.gtinscanner.core.ReferenceStore
import com.sanford.gtinscanner.core.SessionLog
import com.sanford.gtinscanner.core.StagingState
import org.json.JSONObject

/**
 * One SQLite file holds everything that must survive the app being killed:
 * the upload queue, the contract-line mirror (plus its staging copy) and the
 * per-session scan history. `synchronous=FULL` because a scan the operator
 * has seen acknowledged must not vanish on a battery pull.
 */
class Database(context: Context) : SQLiteOpenHelper(context, "gtin-scanner.db", null, 1) {

    val opQueue: OpQueue = SqlOpQueue()
    val reference: ReferenceStore = SqlReferenceStore()
    val sessionLog: SessionLog = SqlSessionLog()

    override fun onConfigure(db: SQLiteDatabase) {
        db.enableWriteAheadLogging()
    }

    override fun onOpen(db: SQLiteDatabase) {
        db.rawQuery("PRAGMA synchronous=FULL", null).use { it.moveToFirst() }
    }

    override fun onCreate(db: SQLiteDatabase) {
        db.execSQL(
            "CREATE TABLE op_queue (seq INTEGER PRIMARY KEY AUTOINCREMENT, " +
                "op_id TEXT NOT NULL UNIQUE, payload TEXT NOT NULL)",
        )
        for (table in listOf("reference", "reference_staging")) {
            db.execSQL(
                "CREATE TABLE $table (gtin TEXT PRIMARY KEY, item TEXT NOT NULL, company TEXT NOT NULL, " +
                    "brand TEXT NOT NULL, description TEXT NOT NULL, gtin_uom TEXT NOT NULL, " +
                    "uou TEXT NOT NULL, lawson_id TEXT NOT NULL, lawson_uom TEXT NOT NULL, " +
                    "on_hold INTEGER NOT NULL)",
            )
        }
        db.execSQL("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
        db.execSQL(
            "CREATE TABLE session_log (session_id TEXT NOT NULL, gtin TEXT NOT NULL, raw_scan TEXT NOT NULL, " +
                "first_at TEXT NOT NULL, last_at TEXT NOT NULL, count INTEGER NOT NULL, row_json TEXT, " +
                "PRIMARY KEY (session_id, gtin))",
        )
    }

    override fun onUpgrade(db: SQLiteDatabase, oldVersion: Int, newVersion: Int) = Unit

    // ── upload queue ─────────────────────────────────────────────────────────
    private inner class SqlOpQueue : OpQueue {
        override fun enqueue(opId: String, payload: String) {
            writableDatabase.insertOrThrow(
                "op_queue", null,
                ContentValues().apply { put("op_id", opId); put("payload", payload) },
            )
        }

        override fun peek(limit: Int): List<QueuedOp> =
            readableDatabase.rawQuery(
                "SELECT seq, op_id, payload FROM op_queue ORDER BY seq LIMIT ?", arrayOf(limit.toString()),
            ).use { c ->
                buildList { while (c.moveToNext()) add(QueuedOp(c.getLong(0), c.getString(1), c.getString(2))) }
            }

        override fun remove(seqs: Collection<Long>) {
            if (seqs.isEmpty()) return
            val db = writableDatabase
            db.beginTransaction()
            try {
                seqs.chunked(500).forEach { chunk ->
                    db.delete("op_queue", "seq IN (${chunk.joinToString(",") { "?" }})", chunk.map { it.toString() }.toTypedArray())
                }
                db.setTransactionSuccessful()
            } finally {
                db.endTransaction()
            }
        }

        override fun size(): Int =
            readableDatabase.rawQuery("SELECT COUNT(*) FROM op_queue", null).use { it.moveToFirst(); it.getInt(0) }
    }

    // ── contract-line mirror ─────────────────────────────────────────────────
    private inner class SqlReferenceStore : ReferenceStore {
        private fun meta(key: String): String? =
            readableDatabase.rawQuery("SELECT value FROM meta WHERE key = ?", arrayOf(key))
                .use { if (it.moveToFirst()) it.getString(0) else null }

        private fun setMeta(db: SQLiteDatabase, key: String, value: String?) {
            if (value == null) {
                db.delete("meta", "key = ?", arrayOf(key))
            } else {
                db.insertWithOnConflict(
                    "meta", null, ContentValues().apply { put("key", key); put("value", value) },
                    SQLiteDatabase.CONFLICT_REPLACE,
                )
            }
        }

        override fun version(): String? = meta("mirror_version")

        override fun lookup(gtin: String): ReferenceRow? =
            readableDatabase.rawQuery(
                "SELECT gtin, item, company, brand, description, gtin_uom, uou, lawson_id, lawson_uom, on_hold " +
                    "FROM reference WHERE gtin = ?",
                arrayOf(gtin),
            ).use { c ->
                if (!c.moveToFirst()) null else ReferenceRow(
                    c.getString(0), c.getString(1), c.getString(2), c.getString(3), c.getString(4),
                    c.getString(5), c.getString(6), c.getString(7), c.getString(8), c.getInt(9) != 0,
                )
            }

        override fun stagingState(): StagingState? {
            val version = meta("staging_version") ?: return null
            return StagingState(version, meta("staging_after"), meta("staging_complete") == "1")
        }

        override fun startStaging(version: String) {
            val db = writableDatabase
            db.beginTransaction()
            try {
                db.delete("reference_staging", null, null)
                setMeta(db, "staging_version", version)
                setMeta(db, "staging_after", null)
                setMeta(db, "staging_complete", "0")
                db.setTransactionSuccessful()
            } finally {
                db.endTransaction()
            }
        }

        override fun appendStaged(rows: List<ReferenceRow>, next: String?) {
            val db = writableDatabase
            db.beginTransaction()
            try {
                val insert = db.compileStatement(
                    "INSERT OR REPLACE INTO reference_staging VALUES (?,?,?,?,?,?,?,?,?,?)",
                )
                for (r in rows) {
                    insert.clearBindings()
                    insert.bindString(1, r.gtin); insert.bindString(2, r.item); insert.bindString(3, r.company)
                    insert.bindString(4, r.brand); insert.bindString(5, r.description); insert.bindString(6, r.gtinUom)
                    insert.bindString(7, r.uou); insert.bindString(8, r.lawsonId); insert.bindString(9, r.lawsonUom)
                    insert.bindLong(10, if (r.onHold) 1 else 0)
                    insert.executeInsert()
                }
                // The cursor moves in the same transaction as its rows, so a
                // crash can never leave a cursor pointing past rows we lack.
                if (next != null) setMeta(db, "staging_after", next)
                setMeta(db, "staging_complete", if (next == null) "1" else "0")
                db.setTransactionSuccessful()
            } finally {
                db.endTransaction()
            }
        }

        override fun commitStaging() {
            val version = meta("staging_version") ?: return
            val db = writableDatabase
            db.beginTransaction()
            try {
                db.delete("reference", null, null)
                db.execSQL("INSERT INTO reference SELECT * FROM reference_staging")
                db.delete("reference_staging", null, null)
                setMeta(db, "mirror_version", version)
                setMeta(db, "staging_version", null)
                setMeta(db, "staging_after", null)
                setMeta(db, "staging_complete", null)
                db.setTransactionSuccessful()
            } finally {
                db.endTransaction()
            }
        }

        override fun discardStaging() {
            val db = writableDatabase
            db.beginTransaction()
            try {
                db.delete("reference_staging", null, null)
                setMeta(db, "staging_version", null)
                setMeta(db, "staging_after", null)
                setMeta(db, "staging_complete", null)
                db.setTransactionSuccessful()
            } finally {
                db.endTransaction()
            }
        }
    }

    // ── per-session history ──────────────────────────────────────────────────
    private inner class SqlSessionLog : SessionLog {
        override fun recordScan(sessionId: String, gtin: String, rawScan: String, at: String, row: ReferenceRow?): LogEntry {
            val db = writableDatabase
            db.beginTransaction()
            try {
                val existing = entry(db, sessionId, gtin)
                val updated = if (existing == null) {
                    LogEntry(gtin, rawScan, at, at, 1, row)
                } else {
                    existing.copy(lastScannedAt = at, count = existing.count + 1)
                }
                db.insertWithOnConflict(
                    "session_log", null,
                    ContentValues().apply {
                        put("session_id", sessionId); put("gtin", gtin); put("raw_scan", updated.rawScan)
                        put("first_at", updated.firstScannedAt); put("last_at", updated.lastScannedAt)
                        put("count", updated.count); put("row_json", updated.row?.let(::rowToJson))
                    },
                    SQLiteDatabase.CONFLICT_REPLACE,
                )
                db.setTransactionSuccessful()
                return updated
            } finally {
                db.endTransaction()
            }
        }

        override fun entries(sessionId: String): List<LogEntry> =
            readableDatabase.rawQuery(
                "SELECT gtin, raw_scan, first_at, last_at, count, row_json FROM session_log " +
                    "WHERE session_id = ? ORDER BY first_at",
                arrayOf(sessionId),
            ).use { c -> buildList { while (c.moveToNext()) add(fromCursor(c)) } }

        private fun entry(db: SQLiteDatabase, sessionId: String, gtin: String): LogEntry? =
            db.rawQuery(
                "SELECT gtin, raw_scan, first_at, last_at, count, row_json FROM session_log " +
                    "WHERE session_id = ? AND gtin = ?",
                arrayOf(sessionId, gtin),
            ).use { if (it.moveToFirst()) fromCursor(it) else null }

        private fun fromCursor(c: android.database.Cursor) = LogEntry(
            c.getString(0), c.getString(1), c.getString(2), c.getString(3), c.getInt(4),
            c.getString(5)?.let(::rowFromJson),
        )
    }

    private fun rowToJson(r: ReferenceRow) = JSONObject()
        .put("gtin", r.gtin).put("item", r.item).put("company", r.company).put("brand", r.brand)
        .put("description", r.description).put("gtin_uom", r.gtinUom).put("uou", r.uou)
        .put("lawson_id", r.lawsonId).put("lawson_uom", r.lawsonUom).put("on_hold", r.onHold)
        .toString()

    private fun rowFromJson(text: String): ReferenceRow {
        val o = JSONObject(text)
        return ReferenceRow(
            o.getString("gtin"), o.getString("item"), o.getString("company"), o.getString("brand"),
            o.getString("description"), o.getString("gtin_uom"), o.getString("uou"),
            o.getString("lawson_id"), o.getString("lawson_uom"), o.getBoolean("on_hold"),
        )
    }
}
