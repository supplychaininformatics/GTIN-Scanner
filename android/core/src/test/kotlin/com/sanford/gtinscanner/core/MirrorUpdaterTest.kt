package com.sanford.gtinscanner.core

import java.io.IOException
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertIs
import kotlin.test.assertNotNull
import kotlin.test.assertNull

class MirrorUpdaterTest {
    private val g = listOf("00000000000001", "00000000000002", "00000000000003", "00000000000004", "00000000000005")

    /** A server holding [g], paged at whatever `limit` asks for. */
    private fun server(version: String = "v1", failOnPage: Int? = null): ScriptedTransport {
        var pageNo = 0
        return ScriptedTransport { _, path, q, _ ->
            when (path) {
                "/v1/reference/version" -> versionResponse(version)
                else -> {
                    pageNo++
                    if (pageNo == failOnPage) offline()
                    if (q["version"] != version) return@ScriptedTransport HttpResult(409, "{}")
                    val limit = q.getValue("limit").toInt()
                    val start = q["after"]?.let { a -> g.indexOfFirst { it > a } } ?: 0
                    val chunk = g.drop(start).take(limit)
                    val more = start + limit < g.size
                    rowsPage(chunk, if (more) chunk.last() else null, version)
                }
            }
        }
    }

    @Test fun `downloads every page and commits`() {
        val store = InMemoryReferenceStore()
        val result = MirrorUpdater(server(), store, pageSize = 2).update()
        assertEquals(MirrorResult.Updated("v1"), result)
        assertEquals("v1", store.version())
        assertEquals(5, store.size())
        assertNotNull(store.lookup("00000000000003"))
    }

    @Test fun `up to date when the version matches - no page requests`() {
        val store = InMemoryReferenceStore()
        MirrorUpdater(server(), store, pageSize = 2).update()
        val t = server()
        assertEquals(MirrorResult.UpToDate("v1"), MirrorUpdater(t, store, pageSize = 2).update())
        assertEquals(1, t.calls.size)
    }

    @Test fun `a dropped connection keeps progress and resumes from the cursor`() {
        val store = InMemoryReferenceStore()
        // Page 1 succeeds (2 rows), page 2 drops.
        val first = server(failOnPage = 2)
        assertEquals(MirrorResult.Offline, MirrorUpdater(first, store, pageSize = 2).update())
        assertNull(store.version(), "live mirror must not change until the last page arrives")
        assertEquals("00000000000002", store.stagingState()!!.after)

        val second = server()
        assertEquals(MirrorResult.Updated("v1"), MirrorUpdater(second, store, pageSize = 2).update())
        val pageRequests = second.calls.filter { it.second == "/v1/reference/contract-lines" }
        assertEquals("00000000000002", pageRequests.first().third["after"], "resumed, did not restart")
        assertEquals(5, store.size())
    }

    @Test fun `offline at the version check changes nothing`() {
        val store = InMemoryReferenceStore()
        val t = ScriptedTransport { _, _, _, _ -> offline() }
        assertEquals(MirrorResult.Offline, MirrorUpdater(t, store).update())
        assertNull(store.stagingState())
    }

    @Test fun `version change mid-download restarts against the new version`() {
        val store = InMemoryReferenceStore()
        var version = "v1"
        var pages = 0
        val t = ScriptedTransport { _, path, q, _ ->
            if (path == "/v1/reference/version") return@ScriptedTransport versionResponse(version)
            pages++
            if (pages == 2) version = "v2" // data refreshes after the first page
            if (q["version"] != version) return@ScriptedTransport HttpResult(409, "{}")
            rowsPage(g.take(1), if (version == "v1") g[0] else null, version)
        }
        assertEquals(MirrorResult.Updated("v2"), MirrorUpdater(t, store, pageSize = 1).update())
        assertEquals("v2", store.version())
        assertEquals(1, store.size(), "no rows from the abandoned v1 download survive")
    }

    @Test fun `gives up when the version keeps changing`() {
        val t = ScriptedTransport { _, path, _, _ ->
            if (path == "/v1/reference/version") versionResponse("v1") else HttpResult(409, "{}")
        }
        val result = MirrorUpdater(t, InMemoryReferenceStore(), maxRestarts = 2).update()
        assertEquals(MirrorResult.ServerError(409), result)
    }

    @Test fun `crash after the last page but before commit finishes without re-downloading`() {
        val store = InMemoryReferenceStore()
        store.startStaging("v1")
        store.appendStaged(g.map(::ref), null) // last page stored, commit never ran
        val t = server()
        assertEquals(MirrorResult.Updated("v1"), MirrorUpdater(t, store).update())
        assertEquals(1, t.calls.size, "only the version check")
        assertEquals(5, store.size())
    }

    @Test fun `auth failure, rate limit and server errors are reported, not thrown`() {
        fun run(status: Int, retryAfter: Int? = null) =
            MirrorUpdater(ScriptedTransport { _, _, _, _ -> HttpResult(status, "{}", retryAfter) }, InMemoryReferenceStore()).update()
        assertEquals(MirrorResult.AuthFailed, run(401))
        assertEquals(MirrorResult.RateLimited(30), run(429, 30))
        assertIs<MirrorResult.ServerError>(run(503))
    }

    @Test fun `stale staging for an old version is replaced`() {
        val store = InMemoryReferenceStore()
        store.startStaging("old")
        store.appendStaged(listOf(ref("99999999999999")), "99999999999999")
        MirrorUpdater(server(), store, pageSize = 10).update()
        assertNull(store.lookup("99999999999999"))
        assertEquals(5, store.size())
    }
}
