package com.sanford.gtinscanner.core

import org.json.JSONArray
import org.json.JSONObject
import kotlin.test.Test
import kotlin.test.assertEquals

class SyncEngineTest {
    private fun queueOf(n: Int): InMemoryOpQueue {
        val q = InMemoryOpQueue()
        repeat(n) { q.enqueue("op-$it-xxxxxxxx", JSONObject().put("type", "scan").put("op_id", "op-$it-xxxxxxxx").toString()) }
        return q
    }

    /** Server that answers every op with [statusFor](opId). */
    private fun serverAnswering(statusFor: (String) -> String) = ScriptedTransport { _, _, _, body ->
        val ops = JSONObject(body!!).getJSONArray("ops")
        val results = JSONArray()
        for (i in 0 until ops.length()) {
            val id = ops.getJSONObject(i).getString("op_id")
            val s = statusFor(id)
            results.put(JSONObject().put("op_id", id).put("status", s).also { if (s == "rejected") it.put("code", "too_old") })
        }
        ok(JSONObject().put("server_time", "now").put("results", results))
    }

    @Test fun `applied ops leave the queue`() {
        val q = queueOf(3)
        val r = SyncEngine(serverAnswering { "applied" }, q).syncOnce()
        assertEquals(SyncStatus.DRAINED, r.status)
        assertEquals(3, r.applied)
        assertEquals(0, q.size())
    }

    @Test fun `duplicates and rejections also leave the queue, rejections are reported`() {
        val q = queueOf(3)
        val r = SyncEngine(serverAnswering { if (it.startsWith("op-0")) "duplicate" else if (it.startsWith("op-1")) "rejected" else "applied" }, q).syncOnce()
        assertEquals(SyncStatus.DRAINED, r.status)
        assertEquals(1, r.duplicates)
        assertEquals(listOf(Rejection("op-1-xxxxxxxx", "too_old")), r.rejected)
        assertEquals(0, q.size())
    }

    @Test fun `retry ops stay queued and stop the run`() {
        val q = queueOf(3)
        val r = SyncEngine(serverAnswering { if (it.startsWith("op-1")) "retry" else "applied" }, q).syncOnce()
        assertEquals(SyncStatus.PARTIAL, r.status)
        assertEquals(listOf("op-1-xxxxxxxx"), q.ops.map { it.opId })
        assertEquals(1, r.remaining)
    }

    @Test fun `an unknown status is treated as retry, never as done`() {
        val q = queueOf(1)
        val r = SyncEngine(serverAnswering { "from-the-future" }, q).syncOnce()
        assertEquals(SyncStatus.PARTIAL, r.status)
        assertEquals(1, q.size())
    }

    @Test fun `no connection leaves everything queued`() {
        val q = queueOf(2)
        val r = SyncEngine(ScriptedTransport { _, _, _, _ -> offline() }, q).syncOnce()
        assertEquals(SyncStatus.OFFLINE, r.status)
        assertEquals(2, q.size())
    }

    @Test fun `large queues go out in batches of at most 100`() {
        val q = queueOf(250)
        val t = serverAnswering { "applied" }
        val r = SyncEngine(t, q).syncOnce()
        assertEquals(SyncStatus.DRAINED, r.status)
        assertEquals(3, t.calls.size)
        assertEquals(250, r.applied)
    }

    @Test fun `ops are sent oldest first`() {
        val q = queueOf(3)
        var sent = listOf<String>()
        SyncEngine(ScriptedTransport { _, _, _, body ->
            val ops = JSONObject(body!!).getJSONArray("ops")
            sent = (0 until ops.length()).map { ops.getJSONObject(it).getString("op_id") }
            serverAnswering { "applied" }.postJson("/v1/sync", body)
        }, q).syncOnce()
        assertEquals(listOf("op-0-xxxxxxxx", "op-1-xxxxxxxx", "op-2-xxxxxxxx"), sent)
    }

    @Test fun `non-200 responses process nothing and keep the queue`() {
        for ((status, expected) in listOf(
            401 to SyncStatus.AUTH_FAILED, 429 to SyncStatus.RATE_LIMITED, 503 to SyncStatus.SERVER_ERROR,
            500 to SyncStatus.SERVER_ERROR, 400 to SyncStatus.PROTOCOL_ERROR, 413 to SyncStatus.PROTOCOL_ERROR,
        )) {
            val q = queueOf(2)
            val r = SyncEngine(ScriptedTransport { _, _, _, _ -> HttpResult(status, "{}", 30) }, q).syncOnce()
            assertEquals(expected, r.status, "HTTP $status")
            assertEquals(2, q.size(), "HTTP $status")
        }
    }

    @Test fun `rate limit carries Retry-After`() {
        val r = SyncEngine(ScriptedTransport { _, _, _, _ -> HttpResult(429, "{}", 45) }, queueOf(1)).syncOnce()
        assertEquals(45, r.retryAfterSeconds)
    }

    @Test fun `a response that does not line up with the request removes nothing`() {
        val q = queueOf(2)
        val short = ScriptedTransport { _, _, _, _ ->
            ok(JSONObject().put("results", JSONArray().put(JSONObject().put("op_id", "op-0-xxxxxxxx").put("status", "applied"))))
        }
        assertEquals(SyncStatus.PROTOCOL_ERROR, SyncEngine(short, q).syncOnce().status)
        val wrongId = ScriptedTransport { _, _, _, _ ->
            ok(JSONObject().put("results", JSONArray()
                .put(JSONObject().put("op_id", "other").put("status", "applied"))
                .put(JSONObject().put("op_id", "op-1-xxxxxxxx").put("status", "applied"))))
        }
        assertEquals(SyncStatus.PROTOCOL_ERROR, SyncEngine(wrongId, q).syncOnce().status)
        assertEquals(2, q.size())
    }

    @Test fun `garbage response body is a protocol error`() {
        val q = queueOf(1)
        assertEquals(SyncStatus.PROTOCOL_ERROR, SyncEngine(ScriptedTransport { _, _, _, _ -> HttpResult(200, "<html>") }, q).syncOnce().status)
        assertEquals(1, q.size())
    }

    @Test fun `empty queue does not call the server`() {
        val t = serverAnswering { "applied" }
        assertEquals(SyncStatus.DRAINED, SyncEngine(t, InMemoryOpQueue()).syncOnce().status)
        assertEquals(0, t.calls.size)
    }
}
