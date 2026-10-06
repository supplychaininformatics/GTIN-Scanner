package com.sanford.gtinscanner.core

import kotlin.test.Test
import kotlin.test.assertEquals

class Gs1Test {
    @Test fun `bare gtin is returned trimmed`() =
        assertEquals("00841098765432", Gs1.extractGtin("  00841098765432 "))

    @Test fun `composite barcode yields the 14 digits after AI 01`() =
        assertEquals("00841098765432", Gs1.extractGtin("0100841098765432" + "10LOT42"))

    @Test fun `symbology identifier prefix is skipped`() =
        assertEquals("00841098765432", Gs1.extractGtin("]d20100841098765432"))

    @Test fun `short gtin is returned as scanned - no padding`() =
        assertEquals("801741030024", Gs1.extractGtin("801741030024"))

    @Test fun `01 with fewer than 14 digits is not a composite`() =
        assertEquals("0112345", Gs1.extractGtin("0112345"))

    @Test fun `group separator is trimmed like the server does`() =
        assertEquals("0084109", Gs1.extractGtin("0084109\u001d"))
}
