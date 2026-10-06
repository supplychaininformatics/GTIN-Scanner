package com.sanford.gtinscanner.core

import java.net.HttpURLConnection
import java.net.URI
import java.net.URLEncoder
import java.util.zip.GZIPInputStream

/**
 * [Transport] over java.net.HttpURLConnection, which exists on both Android and
 * the JVM. HTTPS is required unless [allowCleartext] is set (local dev only) —
 * the bearer token would otherwise cross the network in the clear.
 */
class HttpUrlConnectionTransport(
    baseUrl: String,
    private val token: String,
    allowCleartext: Boolean = false,
    private val connectTimeoutMs: Int = 10_000,
    private val readTimeoutMs: Int = 30_000,
) : Transport {
    private val base: String = baseUrl.trimEnd('/')

    init {
        require(base.startsWith("https://") || (allowCleartext && base.startsWith("http://"))) {
            "Sync URL must be https://"
        }
    }

    override fun get(path: String, query: Map<String, String>): HttpResult {
        val qs = if (query.isEmpty()) "" else
            "?" + query.entries.joinToString("&") { (k, v) -> "${enc(k)}=${enc(v)}" }
        val conn = open("$base$path$qs")
        conn.requestMethod = "GET"
        return execute(conn)
    }

    override fun postJson(path: String, body: String): HttpResult {
        val conn = open("$base$path")
        conn.requestMethod = "POST"
        conn.doOutput = true
        conn.setRequestProperty("Content-Type", "application/json")
        conn.outputStream.use { it.write(body.toByteArray(Charsets.UTF_8)) }
        return execute(conn)
    }

    private fun open(url: String): HttpURLConnection {
        val conn = URI(url).toURL().openConnection() as HttpURLConnection
        conn.connectTimeout = connectTimeoutMs
        conn.readTimeout = readTimeoutMs
        conn.instanceFollowRedirects = false
        conn.setRequestProperty("Authorization", "Bearer $token")
        conn.setRequestProperty("Accept", "application/json")
        // Set explicitly, so the response is decompressed here on every platform.
        conn.setRequestProperty("Accept-Encoding", "gzip")
        return conn
    }

    private fun execute(conn: HttpURLConnection): HttpResult {
        try {
            val status = conn.responseCode
            val stream = (if (status >= 400) conn.errorStream else conn.inputStream)
            val text = stream?.use { raw ->
                val decoded = if ("gzip".equals(conn.contentEncoding, ignoreCase = true)) {
                    GZIPInputStream(raw)
                } else {
                    raw
                }
                decoded.readBytes().toString(Charsets.UTF_8)
            } ?: ""
            return HttpResult(status, text, conn.getHeaderField("Retry-After")?.trim()?.toIntOrNull())
        } finally {
            conn.disconnect()
        }
    }

    private fun enc(s: String) = URLEncoder.encode(s, "UTF-8")
}
