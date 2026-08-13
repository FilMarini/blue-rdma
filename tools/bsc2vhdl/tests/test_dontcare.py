# Test methodology:
# - Sweep: Every behavior `parse_sized_literal` implements (binary
#   wildcard patterns, decimal literals, a mixed x/z/defined-digit binary
#   literal, malformed-literal refusal), plus the seven real casez pattern
#   literals lifted from the vendored `SizedFIFO.v` and one synthetic
#   `'bx` literal, proving D-20's single-code-path claim by test.
# - Stimulus: Literal text strings, hand-typed and lifted verbatim from
#   `SizedFIFO.v`.
# - Checks: Exact `(width, value, care_mask)` tuples; `pytest.raises(...,
#   match=...)` naming the offending text on malformed input.
# - Timing: None. This file launches no simulator.
from __future__ import annotations

import pytest

from tools.bsc2vhdl.dontcare import SizedLiteral, parse_sized_literal

# The seven distinct casez wildcard patterns in SizedFIFO.v (lines 120-185),
# spanning both casez statements.
_SIZEDFIFO_PATTERNS = (
    "5'b1????",
    "5'b011?0",
    "5'b010?1",
    "5'b010?0",
    "5'b0010?",
    "5'b0011?",
    "5'b011?1",
)


def test_parse_sized_literal_binary_wildcard() -> None:
    result = parse_sized_literal("5'b1????")
    assert result == SizedLiteral(width=5, value=16, care_mask=16)


def test_parse_sized_literal_decimal() -> None:
    result = parse_sized_literal("32'd633")
    assert result == SizedLiteral(width=32, value=633, care_mask=4294967295)


def test_parse_sized_literal_mixed_x_and_z() -> None:
    result = parse_sized_literal("4'bx01z")
    assert result.width == 4
    assert result.care_mask == 0b0110
    # The don't-care bit positions (3 and 0) read as zero in `value`.
    assert (result.value >> 3) & 1 == 0
    assert (result.value >> 0) & 1 == 0
    assert (result.value >> 2) & 1 == 0
    assert (result.value >> 1) & 1 == 1


def test_parse_sized_literal_rejects_malformed_text() -> None:
    with pytest.raises(ValueError, match="qty8"):
        parse_sized_literal("qty8")


def test_parse_sized_literal_rejects_missing_base_character() -> None:
    with pytest.raises(ValueError, match="8'"):
        parse_sized_literal("8'")


def test_parse_sized_literal_rejects_a_decimal_dont_care_digit() -> None:
    with pytest.raises(ValueError, match="decimal literal cannot carry"):
        parse_sized_literal("8'dx")


@pytest.mark.parametrize("pattern", _SIZEDFIFO_PATTERNS)
def test_parse_sized_literal_covers_every_sizedfifo_pattern(pattern: str) -> None:
    result = parse_sized_literal(pattern)
    assert result.width == 5
    full_mask = (1 << 5) - 1
    assert result.care_mask != full_mask, "every real SizedFIFO.v pattern carries at least one wildcard bit"
    assert result.value & ~result.care_mask == 0, "an uncared bit position must read as zero"


def test_parse_sized_literal_resolves_a_synthetic_x_style_literal_through_the_same_function() -> None:
    # No literal 'bx/'hx/'dx value exists anywhere in the corpus (D-20); this
    # proves the exact same function that resolves SizedFIFO.v's casez
    # wildcards also resolves an x-style literal, so there is genuinely one
    # code path, not two.
    result = parse_sized_literal("8'bxxxx1010")
    assert result.width == 8
    assert result.care_mask == 0b00001111
    assert result.value == 0b00001010


def test_parse_sized_literal_zero_extends_an_underspecified_binary_literal() -> None:
    # mkTransportLayer.v's own `2'b0` case-arm literal: one digit for a
    # two-bit declared width. Verilog zero-extends the missing high bit with
    # a defined 0, never a don't-care, so the arm must read as fully cared
    # (care_mask == full_mask) rather than being misclassified as a casez
    # wildcard.
    result = parse_sized_literal("2'b0")
    assert result == SizedLiteral(width=2, value=0, care_mask=0b11)


def test_parse_sized_literal_zero_extends_a_partial_binary_literal_above_its_lowest_bit() -> None:
    # A digit count between 1 and the full declared width: the given digits
    # stay right-aligned to the least-significant bit, and only the
    # remaining, unwritten high bits are zero-extended.
    result = parse_sized_literal("5'b01")
    assert result == SizedLiteral(width=5, value=0b00001, care_mask=0b11111)
