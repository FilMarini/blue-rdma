"""The single don't-care resolver: sized literals and casez wildcard patterns.

`parse_sized_literal` is the entire don't-care mechanism in this package.
pyverilog surfaces a `casez` wildcard pattern (`5'b1????`) as a plain
`IntConst.value` string with literal `?` characters inside it, no different
in kind from an `'bx`, `'hx`, or `'dz` literal carrying a genuine don't-care
digit. Both are the same text shape: a width, a base character, and a
digit string whose don't-care positions this function must split out. There
is no second pass anywhere in this package for `'bx`-style resolution: the
corpus has zero literal `'bx`/`'hx`/`'dx` values, and whatever function
already splits wildcard bits out of a `casez` pattern string is, by
definition, the thing that resolves them too. A don't-care bit resolves to
0 in `value`; nothing in the corpus depends on the choice, and a stated
rule beats an accidental one.
"""
from __future__ import annotations

from dataclasses import dataclass

_BASES = {"b": 2, "o": 8, "d": 10, "h": 16}
_BITS_PER_DIGIT = {2: 1, 8: 3, 16: 4}
_UNCARED_CHARS = frozenset("?xXzZ")


@dataclass(frozen=True)
class SizedLiteral:
    """A parsed sized literal: its declared width, its defined value with
    every don't-care bit resolved to 0, and a per-bit care mask (1 where the
    literal names a defined bit, 0 where it named a don't-care)."""

    width: int
    value: int
    care_mask: int


def parse_sized_literal(text: str) -> SizedLiteral:
    """Parse a Verilog sized literal such as "5'b1????" or "32'd633".

    Splits on the apostrophe, reads the optional width before it and the
    base character after it (`b`/`o`/`d`/`h`, case-insensitive), then walks
    the digits most-significant first. `?`, `x`, `X`, `z`, and `Z` are
    treated as don't-care over that digit's whole bit group: they clear the
    corresponding `care_mask` bits and leave the matching `value` bits at 0.
    Underscores in the digit string are ignored, as in Verilog. Raises
    `ValueError` naming the offending text on a malformed literal or an
    unrecognized base.
    """
    original = text
    text = text.strip()
    if "'" not in text:
        raise ValueError(f"malformed sized literal {original!r}: missing base separator")

    width_text, rest = text.split("'", 1)
    width_text = width_text.strip()
    width = 32 if width_text == "" else _parse_width(width_text, original)

    if not rest:
        raise ValueError(f"malformed sized literal {original!r}: missing base character")
    base_char = rest[0].lower()
    if base_char not in _BASES:
        raise ValueError(f"malformed sized literal {original!r}: unrecognized base {rest[0]!r}")
    base = _BASES[base_char]
    digits = rest[1:].replace("_", "")
    if not digits:
        raise ValueError(f"malformed sized literal {original!r}: no digits after the base character")

    full_mask = (1 << width) - 1
    if base == 10:
        return SizedLiteral(width=width, value=_parse_decimal(digits, original) & full_mask, care_mask=full_mask)

    step = _BITS_PER_DIGIT[base]
    value = 0
    care_mask = 0
    bit_pos = width
    for ch in digits:
        bit_pos -= step
        if ch in _UNCARED_CHARS:
            continue
        try:
            digit_value = int(ch, base)
        except ValueError as exc:
            raise ValueError(f"malformed sized literal {original!r}: bad digit {ch!r}") from exc
        value |= digit_value << bit_pos
        care_mask |= ((1 << step) - 1) << bit_pos

    return SizedLiteral(width=width, value=value & full_mask, care_mask=care_mask & full_mask)


def _parse_width(width_text: str, original: str) -> int:
    if not width_text.isdigit():
        raise ValueError(f"malformed sized literal {original!r}: no width before the base character")
    return int(width_text)


def _parse_decimal(digits: str, original: str) -> int:
    if any(ch in _UNCARED_CHARS for ch in digits):
        raise ValueError(f"malformed sized literal {original!r}: a decimal literal cannot carry a don't-care digit")
    try:
        return int(digits, 10)
    except ValueError as exc:
        raise ValueError(f"malformed sized literal {original!r}: bad decimal digits") from exc
