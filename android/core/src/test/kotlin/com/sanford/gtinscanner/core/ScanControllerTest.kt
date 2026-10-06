package com.sanford.gtinscanner.core

import java.time.Instant
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertIs
import kotlin.test.assertNull
import kotlin.test.assertTrue

class ScanControllerTest {
    private val queue = InMemoryOpQueue()
    private val store = InMemoryReferenceStore().also {
        it.startStaging("v1")
        it.appendStaged(listOf(ref("00841098765432")), null)
        it.commitStaging()
    }
    private val log = InMemorySessionLog()
    private var ids = 0
    private var clock = Instant.parse("2026-09-23T18:00:00.123Z")
    private val controller = ScanController(queue, store, log, { clock }, { "id-${(++ids).toString().padStart(6, '0')}" })

    @Test fun `start session queues a create op with device-minted ids`() {
        val sid = controller.startSession(" S123 ", "DOCK-3")
        val op = queue.payloads().single()
        assertEquals("create_session", op.getString("type"))
        assertEquals(sid, op.getString("session_id"))
        assertEquals("S123", op.getString("sanford_id"))
        assertEquals("2026-09-23T18:00:00Z", op.getString("created_at"))
        assertEquals(queue.ops.single().opId, op.getString("op_id"))
    }

    @Test fun `scan of a mirrored gtin resolves offline and queues the raw scan only`() {
        val sid = controller.startSession("S1", "D")
        val result = controller.onScan(sid, "0100841098765432" + "10LOT")
        val scanned = assertIs<ScanResult.Scanned>(result)
        assertEquals("00841098765432", scanned.gtin)
        assertEquals("Widget", scanned.row!!.description)
        val op = queue.payloads().last()
        assertEquals("scan", op.getString("type"))
        assertEquals("0100841098765432" + "10LOT", op.getString("raw_scan"))
        assertEquals(setOf("type", "op_id", "session_id", "raw_scan", "scanned_at"), op.keySet())
    }

    @Test fun `a mirror miss is provisional - no row - but is still queued for the server`() {
        val sid = controller.startSession("S1", "D")
        val scanned = assertIs<ScanResult.Scanned>(controller.onScan(sid, "00999999999999"))
        assertNull(scanned.row)
        assertEquals(2, queue.size())
    }

    @Test fun `rescan is flagged duplicate, counted, and queued as another op`() {
        val sid = controller.startSession("S1", "D")
        controller.onScan(sid, "00841098765432")
        val again = assertIs<ScanResult.Scanned>(controller.onScan(sid, "00841098765432"))
        assertTrue(again.duplicate)
        assertEquals(2, again.scanCount)
        assertEquals(3, queue.size())
        assertEquals(queue.ops.map { it.opId }.toSet().size, queue.size(), "every op has a distinct id")
    }

    @Test fun `same gtin in a different session is not a duplicate`() {
        val a = controller.startSession("S1", "D")
        val b = controller.startSession("S2", "D")
        controller.onScan(a, "00841098765432")
        assertEquals(false, assertIs<ScanResult.Scanned>(controller.onScan(b, "00841098765432")).duplicate)
    }

    @Test fun `unreadable input is refused and nothing is queued`() {
        val sid = controller.startSession("S1", "D")
        val before = queue.size()
        for (bad in listOf("", "   ", "12\u000034", "1".repeat(300))) {
            assertIs<ScanResult.Invalid>(controller.onScan(sid, bad), "input: ${bad.take(10)}")
        }
        assertEquals(before, queue.size())
    }

    @Test fun `gs1 group separator is accepted in a raw scan`() {
        val sid = controller.startSession("S1", "D")
        assertIs<ScanResult.Scanned>(controller.onScan(sid, "0100841098765432\u001d10LOT"))
    }

    @Test fun `end session queues an end op`() {
        val sid = controller.startSession("S1", "D")
        controller.endSession(sid)
        assertEquals("end_session", queue.payloads().last().getString("type"))
    }

    @Test fun `session form values are validated like the server does`() {
        assertFailsWith<IllegalArgumentException> { controller.startSession("", "D") }
        assertFailsWith<IllegalArgumentException> { controller.startSession("S1", "a\nb") }
        assertFailsWith<IllegalArgumentException> { controller.startSession("x".repeat(65), "D") }
        assertEquals(0, queue.size())
    }

    @Test fun `generated ids satisfy the server's id format`() {
        val q = InMemoryOpQueue()
        val c = ScanController(q, store, log)
        c.startSession("S1", "D")
        val id = q.payloads().single().getString("session_id")
        assertTrue(Regex("^[A-Za-z0-9_-]{8,64}$").matches(id), id)
    }
}
