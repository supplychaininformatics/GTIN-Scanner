package com.sanford.gtinscanner.core

object Gs1 {
    private val COMPOSITE = Regex("^(?:\\][A-Za-z0-9]{2})?01(\\d{14})")

    /**
     * The GTIN in a scanned code — identical to the server's extract_gtin: a
     * GS1 composite (optional symbology identifier, AI 01, 14 digits) yields
     * its 14 digits; anything else is the trimmed string itself.
     */
    fun extractGtin(scanned: String): String {
        val code = scanned.trim()
        return COMPOSITE.find(code)?.groupValues?.get(1) ?: code
    }
}
