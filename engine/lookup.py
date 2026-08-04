"""
engine/lookup.py
~~~~~~~~~~~~~~~~
O(1) in-memory GTIN lookup engine.

Builds a dictionary index from the cached DataFrame on construction.
All subsequent lookups are O(1) dictionary key accesses — no DataFrame
scanning occurs at query time.

Alongside the exact-match index, construction also builds two *diagnostic*
indexes used only by diagnose() to explain a miss (see MISS_* below). They
answer "why did this scan not match?" — a question that was previously
invisible, since every non-match collapsed into a single "Not Found".
Diagnosis never affects what search() returns.
"""

from __future__ import annotations

import bisect
import logging

import pandas as pd

from .gtin import (
    check_digit_valid,
    core,
    describe_indicator,
    indicator,
    normalize,
)

logger = logging.getLogger(__name__)

# ── Miss reasons ─────────────────────────────────────────────────────────────
# Why a scan failed to match a contract line. Recorded on every cache miss
# (including ones the goodID API later resolves), persisted on the scan row,
# and shown on the handheld and in the Excel export.
#
# The point of splitting these out is that they need different responses:
# BAD_GTIN is a scanning problem, PADDING is a normalisation bug, PACKAGING is
# a UI/matching gap, and UNKNOWN_ITEM / OFF_CONTRACT are contract-data gaps
# that belong with contracting rather than the warehouse.
MISS_BAD_GTIN = "bad_gtin"
MISS_PADDING = "padding"
MISS_PACKAGING = "packaging"
MISS_UNKNOWN_ITEM = "unknown_item"
MISS_OFF_CONTRACT = "off_contract"

MISS_LABELS = {
    MISS_BAD_GTIN: "Invalid barcode",
    MISS_PADDING: "Width mismatch",
    MISS_PACKAGING: "Different packaging level",
    MISS_UNKNOWN_ITEM: "Vendor on contract, item not",
    MISS_OFF_CONTRACT: "Vendor not on contract",
}

# Minimum shared leading digits of the 12-digit core before a miss is called
# UNKNOWN_ITEM ("we buy from this vendor") rather than OFF_CONTRACT ("we do
# not").
#
# A GS1 company prefix can be as short as 6 digits, but 6 is unusable as a
# threshold here: with ~78k distinct cores indexed, short prefixes collide by
# chance. Measured against the real contract file (130k lines), the longest
# prefix a *random* valid GTIN shares with any indexed core was:
#
#     0-5 digits  99.74%      7 digits  0.03%  (1 sample in 3000)
#       6 digits   0.23%      8+        never
#
# while two real off-contract items from vendors that are on contract scored
# 11 and 10. 8 therefore sits above the observed noise ceiling and well below
# the real signal. Re-measure if the contract file grows by an order of
# magnitude — the noise floor rises with the number of indexed cores.
MIN_SHARED_PREFIX = 8


class LookupEngine:
    """In-memory GTIN lookup backed by a pre-built dict index.

    Args:
        df: Contract line DataFrame. Must have a 'global_trade_item_number'
            column of dtype str with leading zeros preserved.
    """

    def __init__(self, df: pd.DataFrame) -> None:
        # Build index: GTIN string → row dict. O(n) once at startup.
        #
        # Two GTIN columns are indexed. `global_trade_item_number` is the
        # primary (case/box-level) barcode. `low_uom_code_gtin` is the
        # each/inner-pack barcode printed on a single unit inside the case.
        # A worker may scan either one, so both must resolve to the same
        # contract line. Primary GTINs are indexed first and take precedence;
        # low-UOM GTINs are then added as aliases only where they don't
        # collide with an existing primary GTIN.
        self._index: dict[str, dict] = {}
        aliases: list[tuple[str, dict]] = []

        for _, row in df.iterrows():
            record = row.to_dict()
            primary = self._clean_gtin(record.get("global_trade_item_number"))
            alias = self._clean_gtin(record.get("low_uom_code_gtin"))
            if primary:
                self._index[primary] = record
            if alias:
                aliases.append((alias, record))

        # Apply low-UOM aliases without overwriting any primary GTIN.
        for alias, record in aliases:
            self._index.setdefault(alias, record)

        self._build_diagnostics()

        logger.debug("LookupEngine index built with %d entries.", len(self._index))

    def _build_diagnostics(self) -> None:
        """Build the two indexes diagnose() needs, from the exact index.

        Derived from self._index rather than a second DataFrame pass, so every
        GTIN diagnose() can point at is one search() could also have matched.

        `_by_norm` keys on the zero-padded 14-digit form, which is what makes
        the PADDING bucket detectable: a contract row stored as 13 digits and a
        scan arriving as 14 collapse to the same key here while remaining
        different strings to search().

        `_sorted_cores` is a plain sorted list rather than a set of prefix
        slices at every length: the longest prefix any string shares with a
        sorted list is always shared with one of its two insertion-point
        neighbours, so bisect answers it in O(log n) with no extra memory.
        """
        self._by_norm: dict[str, list[tuple[str, dict]]] = {}
        self._by_core: dict[str, list[tuple[str, dict]]] = {}

        for raw_gtin, record in self._index.items():
            norm = normalize(raw_gtin)
            if not norm:
                continue
            self._by_norm.setdefault(norm, []).append((raw_gtin, record))
            self._by_core.setdefault(core(norm), []).append((norm, record))

        self._sorted_cores: list[str] = sorted(self._by_core)

    def _longest_shared_prefix(self, body: str) -> int:
        """Digits `body` shares with the closest known core (see _build_diagnostics)."""
        if not body or not self._sorted_cores:
            return 0
        pos = bisect.bisect_left(self._sorted_cores, body)
        best = 0
        for neighbour in self._sorted_cores[max(0, pos - 1):pos + 2]:
            shared = 0
            # strict=False is the point: comparison stops at the shorter of
            # the two, which is exactly "how many leading digits match".
            for a, b in zip(body, neighbour, strict=False):
                if a != b:
                    break
                shared += 1
            best = max(best, shared)
        return best

    @staticmethod
    def _clean_gtin(value: object) -> str:
        """Normalise a GTIN cell to a lookup key, or '' if empty/NaN.

        Empty low-UOM cells arrive from the source as float NaN (which
        stringifies to 'nan'), so those must be filtered out rather than
        indexed as the literal key 'nan'.
        """
        if value is None:
            return ""
        s = str(value).strip()
        if s.lower() in ("", "nan", "none"):
            return ""
        return s

    def search(self, gtin: str) -> dict | None:
        """Look up a GTIN in the in-memory index.

        Leading zeros are preserved exactly as scanned. The only
        normalisation applied is stripping surrounding whitespace,
        which guards against scanner firmware that pads with spaces.

        Args:
            gtin: Raw GTIN string from the barcode scanner.

        Returns:
            The matching contract line record as a dict, or None if not found.
        """
        return self._index.get(gtin.strip())

    def diagnose(self, gtin: str) -> dict:
        """Explain why `gtin` did not match a contract line.

        Only meaningful after search() has returned None — it assumes a miss
        and does not re-check. Returns a dict with:

            reason  one of the MISS_* constants
            label   the short human label for `reason`
            detail  one line of specific evidence, safe to show or export

        The buckets are ordered most-actionable first, and the order matters:
        a barcode that fails its own check digit is diagnosed as a bad scan
        before the contract is consulted at all, so a misread can never be
        reported as a contract-data gap.

        PACKAGING is advisory only. It means "a GTIN sharing this item's core
        is on contract at a different packaging level" — strong evidence under
        the usual GS1 convention, but not a guarantee the two are the same
        trade item (see engine/gtin.py). A case and an each are different
        orderable units with different prices and UOMs, so the sibling is
        surfaced as a hint and never written into the scan's own item fields.
        """
        raw = (gtin or "").strip()
        norm = normalize(raw)

        if not norm:
            return self._miss(
                MISS_BAD_GTIN, f"{len(raw)} chars — not a GTIN-8/12/13/14"
            )
        if not check_digit_valid(norm):
            return self._miss(MISS_BAD_GTIN, "check digit failed — likely a misread")

        # Same identifier, different stored width. Distinct from PACKAGING:
        # nothing about the item differs, only how the contract file spells it.
        padded = self._by_norm.get(norm)
        if padded:
            widths = sorted({str(len(g)) for g, _ in padded})
            return self._miss(
                MISS_PADDING,
                f"on contract as {padded[0][0]} "
                f"({'/'.join(widths)}-digit) — scanned as {len(raw)}-digit",
            )

        siblings = self._by_core.get(core(norm))
        if siblings:
            scanned_level = describe_indicator(indicator(norm))
            shown = ", ".join(
                f"{sib} ({describe_indicator(indicator(sib))}"
                f"{self._lawson_suffix(record)})"
                for sib, record in siblings[:2]
            )
            more = f" +{len(siblings) - 2} more" if len(siblings) > 2 else ""
            return self._miss(
                MISS_PACKAGING,
                f"scanned {scanned_level}; on contract as {shown}{more}",
            )

        shared = self._longest_shared_prefix(core(norm))
        digits = "digit" if shared == 1 else "digits"
        if shared >= MIN_SHARED_PREFIX:
            return self._miss(
                MISS_UNKNOWN_ITEM,
                f"vendor prefix matches {shared} {digits} — item not on contract",
            )
        return self._miss(
            MISS_OFF_CONTRACT,
            f"no vendor prefix match (closest is {shared} {digits})",
        )

    @staticmethod
    def _miss(reason: str, detail: str) -> dict:
        return {"reason": reason, "label": MISS_LABELS[reason], "detail": detail}

    @staticmethod
    def _lawson_suffix(record: dict) -> str:
        """', Lawson 6112009' for a record that has one, else ''."""
        value = record.get("item_number")
        if value is None or pd.isna(value):
            return ""
        text = str(value).strip()
        return f", Lawson {text}" if text else ""

    @property
    def size(self) -> int:
        """Return the number of indexed contract lines."""
        return len(self._index)
