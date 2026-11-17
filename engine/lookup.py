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
import re

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
# a UI/matching gap, and NO_CONTRACT_LINE is a data gap to investigate.
#
# Each bucket asserts only what the code actually proved. In particular there
# is deliberately NO "off contract" bucket, and the surviving one is named for
# the *lookup* rather than the item. Everything in the warehouse is on some
# contract by definition — it could not have been bought otherwise — so a miss
# is never evidence that an item is off contract. It means the barcode is not
# in the contract file this app loaded, which happens routinely to fully
# contracted stock: the source row's GTIN cell is blank or stale, the
# manufacturer re-barcoded the same item, the line sits on a contract outside
# this load's scope (consignment, bill-only, another tier), or the cache
# predates the item being added. Naming the bucket after the file keeps it a
# finding to chase rather than a verdict on the item.
MISS_BAD_GTIN = "bad_gtin"
MISS_PADDING = "padding"
MISS_PACKAGING = "packaging"
MISS_NO_CONTRACT_LINE = "no_contract_line"

MISS_LABELS = {
    MISS_BAD_GTIN: "Invalid barcode",
    MISS_PADDING: "Width mismatch",
    MISS_PACKAGING: "Different packaging level",
    MISS_NO_CONTRACT_LINE: "No contract line for this barcode",
}

# Display threshold only: below this many shared leading digits, the closest
# indexed core is coincidence and naming it would hand a buyer a false lead.
# It selects nothing and changes no bucket — every miss below it reports the
# same reason as every miss above it, just without the pointer.
#
# A GS1 company prefix can be as short as 6 digits, but 6 is unusable here:
# with ~78k distinct cores indexed, short prefixes collide by chance. Measured
# against the real contract file (130k lines), the longest prefix a *random*
# valid GTIN shared with any indexed core was:
#
#     0-5 digits  99.74%      7 digits  0.03%  (1 sample in 3000)
#       6 digits   0.23%      8+        never
#
# while two real items from vendors already on contract scored 11 and 10. 8
# therefore sits above the observed noise ceiling and well below the real
# signal. Re-measure if the contract file grows by an order of magnitude — the
# noise floor rises with the number of indexed cores.
LEAD_MIN_SHARED = 8

# Excel renders a long digit string as "9.89803E+11" and a part number like
# JUN-10 as a date. Both are unrecoverable, and the first one collides across
# dozens of unrelated items, so such values are never indexed as catalog numbers.
_SCI_NOTATION = re.compile(r"^\d+(\.\d+)?E\+\d+$", re.IGNORECASE)


def _catalog_key(value: object) -> str:
    """Manufacturer catalog number as an exact-match key: trimmed, upper-cased.

    '' for blanks and for values that look Excel-mangled (see _SCI_NOTATION).
    """
    if value is None or pd.isna(value):
        return ""
    text = str(value).strip().upper()
    if not text or _SCI_NOTATION.match(text):
        return ""
    return text


def _loose(text: str) -> str:
    """Alphanumerics only, so 'AB-123' and 'AB 123' compare equal."""
    return re.sub(r"[^A-Z0-9]", "", text)


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
        self._build_catalog_index(df)

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

    def _build_catalog_index(self, df: pd.DataFrame) -> None:
        """Index contract-line records by manufacturer catalog number.

        Two keys per record (vendor_item and manufacturer_number), each in an
        exact and an alphanumerics-only form. Used only by find_by_catalog().
        """
        self._by_catalog: dict[str, list[dict]] = {}
        self._by_catalog_loose: dict[str, list[dict]] = {}
        for record in df.to_dict("records"):
            for col in ("vendor_item", "manufacturer_number"):
                key = _catalog_key(record.get(col))
                if not key:
                    continue
                self._by_catalog.setdefault(key, []).append(record)
                loose = _loose(key)
                if loose:
                    self._by_catalog_loose.setdefault(loose, []).append(record)

    @staticmethod
    def _same_maker(record: dict, company: str) -> bool:
        """Loose check that a record's manufacturer is the one named in `company`."""
        company = company.upper()
        for col in ("manufacturer_name", "manufacturer_code"):
            value = record.get(col)
            if value is None or pd.isna(value):
                continue
            first = str(value).strip().upper().split(" ")[0]
            if len(first) >= 3 and first in company:
                return True
        return False

    def find_by_catalog(self, catalog_number: str, company: str = "") -> list[dict]:
        """Contract-line records for a manufacturer catalog number, one per Lawson item.

        Advisory, for resolving a Lawson item after a goodID hit. This is NOT a
        GTIN match: a catalog number can be shared by an each, a box and a case,
        and (rarely) by two manufacturers. Callers must surface every candidate
        rather than pick one.

        Tries the exact (case-insensitive) number first, then ignoring
        punctuation/spaces. When several items match and `company` is given,
        narrows to those whose manufacturer appears in it, but only if that
        leaves at least one.
        """
        key = _catalog_key(catalog_number)
        if not key:
            return []
        matches = self._by_catalog.get(key) or self._by_catalog_loose.get(_loose(key)) or []

        by_item: dict[str, dict] = {}
        uoms: dict[str, set[str]] = {}
        for record in matches:
            item = record.get("item_number")
            if item is None or pd.isna(item) or not str(item).strip():
                continue
            item = str(item).strip()
            by_item.setdefault(item, record)
            uom = record.get("uom_unit_of_measure")
            uoms.setdefault(item, set()).add(
                "" if uom is None or pd.isna(uom) else str(uom).strip()
            )
        # Copies, so the index is never mutated. `catalog_uoms` lets the caller
        # tell whether the item's rows agree on the GTIN UOM.
        found = [
            {**record, "catalog_uoms": uoms[item]} for item, record in by_item.items()
        ]

        if len(found) > 1 and company:
            narrowed = [r for r in found if self._same_maker(r, company)]
            if narrowed:
                found = narrowed
        return found

    def _closest_core(self, body: str) -> tuple[int, str]:
        """Closest known core to `body`, as (shared leading digits, that core).

        Returns (0, "") when nothing is indexed. The core is returned alongside
        the count so diagnose() can name the actual near-miss GTIN rather than
        report a bare digit count — a buyer chasing a missing contract line can
        act on "closest is 00382903891234", not on "shares 11 digits".
        """
        if not body or not self._sorted_cores:
            return 0, ""
        pos = bisect.bisect_left(self._sorted_cores, body)
        best, best_core = 0, ""
        for neighbour in self._sorted_cores[max(0, pos - 1):pos + 2]:
            shared = 0
            # strict=False is the point: comparison stops at the shorter of
            # the two, which is exactly "how many leading digits match".
            for a, b in zip(body, neighbour, strict=False):
                if a != b:
                    break
                shared += 1
            if shared > best:
                best, best_core = shared, neighbour
        return best, best_core

    def entries(self) -> list[tuple[str, dict]]:
        """Every (index key, contract-line record) pair, sorted by key.

        The keys are exactly what search() matches on, so a client mirroring
        these pairs can resolve a scan with the same exact-match lookup.
        """
        return sorted(self._index.items())

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

        NO_CONTRACT_LINE is the fallthrough, and it is a statement about this
        app's contract file rather than about the item — see the MISS_*
        comments above for why a miss is never evidence that something is off
        contract. Its detail may name the closest indexed GTIN as a lead.

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

        # One bucket, and the detail is an observation rather than a claim: the
        # nearest indexed GTIN is a lead for whoever chases the missing line,
        # not a statement about who supplies the item. Below LEAD_MIN_SHARED
        # there is no lead worth printing, but the reason is unchanged.
        shared, closest = self._closest_core(core(norm))
        if shared >= LEAD_MIN_SHARED and closest:
            sibling, record = self._by_core[closest][0]
            digits = "digit" if shared == 1 else "digits"
            return self._miss(
                MISS_NO_CONTRACT_LINE,
                f"closest on contract is {sibling}{self._lawson_suffix(record)}"
                f" — shares {shared} leading {digits}",
            )
        return self._miss(
            MISS_NO_CONTRACT_LINE, "no similar GTIN on contract"
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
