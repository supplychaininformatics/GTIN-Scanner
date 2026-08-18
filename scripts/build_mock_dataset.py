"""
scripts/build_mock_dataset.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Turn a raw Fabric contract_line export into the committed mock dataset that
`DATA_SOURCE=mock` reads (data/mock/contract_line.parquet).

The export is whatever the lakehouse query in data/loader.py returns, saved
from Fabric as .xlsx — so it arrives with *lakehouse* column names (item, gtin,
hold, …) rather than the canonical names the rest of the app uses. Everything
this script does is the same normalisation `_load_from_lakehouse()` applies
after a live fetch, done once at build time so the runtime mock path stays a
plain read:

  * rename lakehouse columns to canonical ones (_LAKEHOUSE_COLUMN_MAP)
  * drop the columns the app deliberately never selects (_RETIRED_COLUMNS)
  * turn Fabric's "(blank.)" export placeholder back into a real null

Columns are written as strings, matching the previous mock dataset — the mock
loader coerces on_hold and contract_line to bool/int on read.

Usage:
    python scripts/build_mock_dataset.py ~/Downloads/contract_line_export.xlsx
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data.loader import _LAKEHOUSE_COLUMN_MAP, _RETIRED_COLUMNS  # noqa: E402

DEFAULT_OUTPUT = Path(__file__).resolve().parent.parent / "data" / "mock" / "contract_line.parquet"

# Fabric's Excel export writes this literal string where the column is NULL.
# It has to become a real null before the dataset is indexed: LookupEngine
# filters empty/NaN GTIN cells out of its index, but "(blank.)" is a non-empty
# string, so every null-GTIN row would otherwise collide on one bogus key.
_BLANK_SENTINEL = "(blank.)"


def build(source: Path, output: Path) -> pd.DataFrame:
    """Read a raw lakehouse export and write it as the canonical mock dataset."""
    if source.suffix.lower() == ".parquet":
        df = pd.read_parquet(source)
    else:
        df = pd.read_excel(source, sheet_name="Sheet1", dtype=str)
    print(f"Read {len(df):,} rows from {source} ({len(df.columns)} columns).")

    df = df.rename(columns=_LAKEHOUSE_COLUMN_MAP)
    df = df.drop(columns=["key", *_RETIRED_COLUMNS], errors="ignore")

    blanks = int((df == _BLANK_SENTINEL).sum().sum())
    if blanks:
        df = df.replace(_BLANK_SENTINEL, None)
        print(f"Replaced {blanks:,} {_BLANK_SENTINEL!r} placeholders with nulls.")

    df = df.astype("string")

    output.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(output, index=False)
    size_mb = output.stat().st_size / 1_048_576
    print(f"Wrote {len(df):,} rows to {output} ({size_mb:.1f} MB).")
    print("Columns:", ", ".join(df.columns))
    return df


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Raw Fabric export (.xlsx or .parquet)")
    parser.add_argument(
        "-o", "--output", type=Path, default=DEFAULT_OUTPUT,
        help=f"Destination parquet (default: {DEFAULT_OUTPUT})",
    )
    args = parser.parse_args()

    if not args.source.expanduser().exists():
        parser.error(f"{args.source} does not exist")
    build(args.source.expanduser(), args.output)


if __name__ == "__main__":
    main()
