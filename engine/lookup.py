"""
engine/lookup.py
~~~~~~~~~~~~~~~~
O(1) in-memory GTIN lookup engine.

Builds a dictionary index from the cached DataFrame on construction.
All subsequent lookups are O(1) dictionary key accesses — no DataFrame
scanning occurs at query time.
"""

from __future__ import annotations

import logging

import pandas as pd

logger = logging.getLogger(__name__)


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

        logger.debug("LookupEngine index built with %d entries.", len(self._index))

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

    @property
    def size(self) -> int:
        """Return the number of indexed contract lines."""
        return len(self._index)
