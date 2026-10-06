package com.sanford.gtinscanner.core

import java.io.IOException
import org.json.JSONArray
import org.json.JSONObject

sealed interface MirrorResult {
    data class UpToDate(val version: String) : MirrorResult
    data class Updated(val version: String) : MirrorResult
    /** No connection (or it dropped mid-download; progress is kept and resumes). */
    data object Offline : MirrorResult
    /** The token was refused — needs re-provisioning, not a retry. */
    data object AuthFailed : MirrorResult
    data class RateLimited(val retryAfterSeconds: Int?) : MirrorResult
    data class ServerError(val status: Int) : MirrorResult
}

/**
 * Keeps the on-device contract-line mirror current.
 *
 * The download is paged and resumable: each page and its cursor are stored
 * together, so a WiFi drop costs at most one page. The live mirror is only
 * replaced after the last page has arrived, so a scan never sees a half-updated
 * copy. If the server's data changes mid-download (HTTP 409) the partial copy
 * is discarded and the download restarts against the new version.
 */
class MirrorUpdater(
    private val transport: Transport,
    private val store: ReferenceStore,
    private val pageSize: Int = 2000,
    private val maxRestarts: Int = 3,
) {
    fun update(): MirrorResult {
        var restarts = 0
        restart@ while (true) {
            val versionResponse = try {
                transport.get("/v1/reference/version")
            } catch (e: IOException) {
                return MirrorResult.Offline
            }
            failure(versionResponse)?.let { return it }
            val serverVersion = JSONObject(versionResponse.body).getString("version")

            val staging = store.stagingState()
            if (store.version() == serverVersion) {
                if (staging != null) store.discardStaging()
                return MirrorResult.UpToDate(serverVersion)
            }

            var after: String? = null
            if (staging != null && staging.version == serverVersion) {
                if (staging.complete) {
                    store.commitStaging()
                    return MirrorResult.Updated(serverVersion)
                }
                after = staging.after
            } else {
                store.startStaging(serverVersion)
            }

            while (true) {
                val query = mutableMapOf("version" to serverVersion, "limit" to pageSize.toString())
                after?.let { query["after"] = it }
                val page = try {
                    transport.get("/v1/reference/contract-lines", query)
                } catch (e: IOException) {
                    return MirrorResult.Offline
                }
                if (page.status == 409) {
                    store.discardStaging()
                    if (++restarts > maxRestarts) return MirrorResult.ServerError(409)
                    continue@restart
                }
                failure(page)?.let { return it }

                val json = JSONObject(page.body)
                val next = if (json.isNull("next")) null else json.getString("next")
                store.appendStaged(parseRows(json.getJSONArray("rows")), next)
                if (next == null) break
                after = next
            }
            store.commitStaging()
            return MirrorResult.Updated(serverVersion)
        }
    }

    private fun failure(r: HttpResult): MirrorResult? = when {
        r.status == 200 -> null
        r.status == 401 -> MirrorResult.AuthFailed
        r.status == 429 -> MirrorResult.RateLimited(r.retryAfterSeconds)
        else -> MirrorResult.ServerError(r.status)
    }

    private fun parseRows(array: JSONArray): List<ReferenceRow> =
        (0 until array.length()).map { i ->
            val o = array.getJSONObject(i)
            ReferenceRow(
                gtin = o.getString("gtin"),
                item = o.getString("item"),
                company = o.getString("company"),
                brand = o.getString("brand"),
                description = o.getString("description"),
                gtinUom = o.getString("gtin_uom"),
                uou = o.getString("uou"),
                lawsonId = o.getString("lawson_id"),
                lawsonUom = o.getString("lawson_uom"),
                onHold = o.getBoolean("on_hold"),
            )
        }
}
