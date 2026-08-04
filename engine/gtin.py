"""
engine/gtin.py
~~~~~~~~~~~~~~
Pure GTIN arithmetic. No pandas, no Streamlit, no I/O — so it stays trivially
testable and importable from either `engine` or `core` without a cycle
(core imports engine, never the other way round).

The one concept worth naming here is the **core**: digits 2..13 of a GTIN-14,
i.e. the GS1 company prefix plus the item reference, with the packaging
indicator digit and the check digit both stripped.

    3 070738780464 1
    ^ ^~~~~~~~~~~~ ^
    | core         check digit
    indicator (packaging level)

Two GTINs that share a core are, by the near-universal GS1 convention, the
same trade item at different packaging levels (each / inner pack / case).
"Convention" is doing real work in that sentence: GS1 does not *require* a
manufacturer to keep the item reference stable across packaging levels, so a
core match is strong evidence and not proof. Everything built on core matching
in this codebase is therefore advisory (see LookupEngine.diagnose) and must
never be presented as a contract match.

Note the indicator digit cannot simply be swapped to move between packaging
levels — the check digit is computed over the indicator too, so it changes as
well. Use sibling_gtin() rather than string surgery.
"""

from __future__ import annotations

MIN_LEN = 8
MAX_LEN = 14


def is_digits(value: str) -> bool:
    """True for a non-empty all-ASCII-digit string.

    `str.isdigit()` is True for superscripts and other Unicode digit forms
    ("²".isdigit() is True), which would then blow up int() or silently
    skew the check digit, so the character set is pinned explicitly.
    """
    return bool(value) and all("0" <= c <= "9" for c in value)


def normalize(gtin: str | None) -> str:
    """A GTIN-8/12/13/14 left-padded to its 14-digit form, or '' if unusable.

    GS1 treats GTIN-8/12/13/14 as the same identifier zero-padded to a common
    width, and the contract file mixes widths (a few hundred rows carry 12- or
    13-digit values). Padding here means diagnosis compares like with like.

    This deliberately does NOT validate the check digit — a misread still
    normalises fine, and it is check_digit_valid()'s job to catch it.
    """
    text = (gtin or "").strip()
    if not is_digits(text) or not (MIN_LEN <= len(text) <= MAX_LEN):
        return ""
    return text.zfill(MAX_LEN)


def check_digit(payload: str) -> str:
    """The mod-10 check digit for the first 13 digits of a GTIN-14.

    Weights alternate 3,1,3,1… from the rightmost payload digit leftwards.
    """
    total = sum(
        int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(payload))
    )
    return str((-total) % 10)


def check_digit_valid(gtin: str) -> bool:
    """True if `gtin` normalises and its trailing check digit is correct.

    A False here is the one miss bucket that means "the scan itself is wrong"
    rather than "the data is incomplete", which is why it is tested before any
    contract lookup is attempted.
    """
    norm = normalize(gtin)
    return bool(norm) and check_digit(norm[:-1]) == norm[-1]


def indicator(gtin: str) -> str:
    """The packaging indicator digit: '0' for a base unit (each), '1'-'8' for
    successively higher packaging levels, '9' for variable-measure trade items.
    Empty string if `gtin` does not normalise.
    """
    norm = normalize(gtin)
    return norm[0] if norm else ""


def core(gtin: str) -> str:
    """The 12-digit company-prefix + item-reference core, or '' if unusable.

    This is the join key across packaging levels — see the module docstring.
    """
    norm = normalize(gtin)
    return norm[1:13] if norm else ""


def sibling_gtin(gtin: str, new_indicator: str) -> str:
    """`gtin` re-expressed at another packaging level, check digit recomputed.

    Returns '' if `gtin` does not normalise. Provided so callers never reach
    for the tempting-but-wrong `new_indicator + gtin[1:]`.
    """
    body = core(gtin)
    if not body or not is_digits(new_indicator) or len(new_indicator) != 1:
        return ""
    payload = new_indicator + body
    return payload + check_digit(payload)


def describe_indicator(digit: str) -> str:
    """A human label for a packaging indicator digit, for UI/export text."""
    if digit == "0":
        return "each / base unit"
    if digit == "9":
        return "variable measure"
    if digit and "1" <= digit <= "8":
        return f"packaging level {digit}"
    return "unknown level"
