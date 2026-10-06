package com.sanford.gtinscanner.core

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertIs
import kotlin.test.assertNotNull
import kotlin.test.assertTrue
import org.json.JSONObject
import org.junit.jupiter.api.Assumptions.assumeTrue

/**
 * End-to-end check of this client against the real Python service, so the two
 * sides cannot drift apart on the wire format. Skipped unless a server is given:
 *
 *   DATA_SOURCE=mock python -m sync_api.dev_server          # from the repo root
 *   SYNC_API_URL=http://127.0.0.1:8080 SYNC_API_TOKEN=dev-token ./gradlew :core:test
 */
class LiveServerTest {
    private val url = System.getenv("SYNC_API_URL").orEmpty()
    private val token = System.getenv("SYNC_API_TOKEN").orEmpty()

    @Test fun `mirror download, offline scans, sync, and idempotent resend against the real server`() {
        assumeTrue(url.isNotBlank() && token.isNotBlank(), "SYNC_API_URL/SYNC_API_TOKEN not set")
        val transport = HttpUrlConnectionTransport(url, token, allowCleartext = true)

        // 1. Download the mirror through the real paged endpoint.
        val reference = InMemoryReferenceStore()
        assertIs<MirrorResult.Updated>(MirrorUpdater(transport, reference, pageSize = 5000).update())
        assertTrue(reference.size() > 1000, "mirror has ${reference.size()} rows")
        assertEquals(MirrorResult.UpToDate(reference.version()!!), MirrorUpdater(transport, reference).update())

        // 2. Scan with no server call in between: a mirrored item (as a GS1
        // composite), a rescan of it, and garbage.
        val known = reference.anyRow()
        val queue = InMemoryOpQueue()
        val controller = ScanController(queue, reference, InMemorySessionLog())
        val session = controller.startSession("S-LIVE", "DOCK-LIVE")
        val composite = "01" + known.gtin.padStart(14, '0') + "10LOT"
        val first = assertIs<ScanResult.Scanned>(controller.onScan(session, known.gtin))
        assertNotNull(first.row, "mirrored item resolves offline")
        assertIs<ScanResult.Scanned>(controller.onScan(session, composite))
        assertIs<ScanResult.Scanned>(controller.onScan(session, "not-a-barcode"))
        controller.endSession(session)
        assertEquals(5, queue.size())

        // 3. Sync: the server accepts every op.
        val sent = queue.ops.map { it.opId to it.payload }
        val report = SyncEngine(transport, queue).syncOnce()
        assertEquals(SyncStatus.DRAINED, report.status, report.toString())
        assertEquals(emptyList(), report.rejected)
        assertEquals(5, report.applied)
        assertEquals(0, queue.size())

        // 4. Resending the identical ops (as after a lost response) applies nothing new.
        val resend = InMemoryOpQueue()
        sent.forEach { (id, payload) -> resend.enqueue(id, payload) }
        val again = SyncEngine(transport, resend).syncOnce()
        assertEquals(SyncStatus.DRAINED, again.status)
        assertEquals(0, again.applied, again.toString())
        assertEquals(5, again.duplicates)
        assertEquals(sent.map { it.first }, sent.map { JSONObject(it.second).getString("op_id") })
    }
}
