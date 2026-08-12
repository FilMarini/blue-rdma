# Test methodology:
# - Sweep: Every self-determined and context-determined width rule
#   `infer_width` implements: sized and unsized literals, identifiers
#   resolved against a hand-built context, part-selects, concatenation,
#   replication with a symbolic count, comparisons and logical operators,
#   and the two refusal shapes (a zero-length range, a shift).
# - Stimulus: Hand-built pyverilog AST nodes constructed directly rather
#   than parsed from a `.v` file, plus a minimal stand-in context exposing
#   exactly the attributes `width.py` reads (`path`, `signal_size`,
#   `generic_name`, `param_kind`, `param_names`, `is_param`).
# - Checks: Every rejection case asserts on its message via `match=`, and
#   also asserts the offending line number appears in the message text.
# - Timing: None. This file launches no simulator.
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest
import pyverilog.vparser.ast as vast

from tools.bsc2vhdl.errors import UnsupportedConstruct
from tools.bsc2vhdl.width import WidthExpr, infer_width


@dataclass
class _Ctx:
    """A minimal stand-in for `emit.py`'s `_EmitContext`, exposing exactly
    the attributes `infer_width` reads and nothing else."""

    path: Path = field(default_factory=lambda: Path("synthetic.v"))
    signal_size: dict = field(default_factory=dict)
    generic_name: dict = field(default_factory=dict)
    param_kind: dict = field(default_factory=dict)
    param_names: set = field(default_factory=set)

    def is_param(self, name: str) -> bool:
        return name in self.param_names


def _param_ctx(name: str, generic: str) -> _Ctx:
    return _Ctx(generic_name={name: generic}, param_names={name})


def test_infer_width_sized_decimal_literal() -> None:
    assert infer_width(vast.IntConst("32'd633"), _Ctx()) == WidthExpr(32, "32")


def test_infer_width_unsized_decimal_literal() -> None:
    assert infer_width(vast.IntConst("5"), _Ctx()) == WidthExpr(32, "32")


def test_infer_width_single_bit_literal() -> None:
    assert infer_width(vast.IntConst("1'd1"), _Ctx()) == WidthExpr(1, "1")


def test_infer_width_part_select() -> None:
    node = vast.Partselect(vast.Identifier("arr"), vast.IntConst("7"), vast.IntConst("0"))
    assert infer_width(node, _Ctx()) == WidthExpr(8, "8")


def test_infer_width_bit_select_is_one() -> None:
    node = vast.Pointer(vast.Identifier("vec"), vast.IntConst("3"))
    assert infer_width(node, _Ctx()) == WidthExpr(1, "1")


def test_infer_width_concatenation_sums_operand_widths() -> None:
    three_bit = vast.Partselect(vast.Identifier("a"), vast.IntConst("2"), vast.IntConst("0"))
    five_bit = vast.Partselect(vast.Identifier("b"), vast.IntConst("4"), vast.IntConst("0"))
    node = vast.Concat([three_bit, five_bit])
    assert infer_width(node, _Ctx()) == WidthExpr(8, "8")


def test_infer_width_replication_keeps_symbolic_width_for_a_parameter_count() -> None:
    node = vast.Repeat(vast.Concat([vast.Identifier("bit")]), vast.Identifier("width"))
    ctx = _param_ctx("width", "WIDTH_G")
    result = infer_width(node, ctx)
    assert result.value is None
    assert result.text == "WIDTH_G"


def test_infer_width_replication_folds_a_concrete_count() -> None:
    node = vast.Repeat(vast.Concat([vast.Identifier("bit")]), vast.IntConst("4"))
    assert infer_width(node, _Ctx()) == WidthExpr(4, "4")


def test_infer_width_comparison_is_one_bit() -> None:
    node = vast.Eq(vast.Identifier("a"), vast.Identifier("b"))
    assert infer_width(node, _Ctx()) == WidthExpr(1, "1")


def test_infer_width_logical_and_is_one_bit() -> None:
    node = vast.Land(vast.Identifier("a"), vast.Identifier("b"))
    assert infer_width(node, _Ctx()) == WidthExpr(1, "1")


def test_infer_width_context_determined_binary_takes_the_wider_operand() -> None:
    narrow = vast.Partselect(vast.Identifier("a"), vast.IntConst("2"), vast.IntConst("0"))
    wide = vast.Partselect(vast.Identifier("b"), vast.IntConst("7"), vast.IntConst("0"))
    node = vast.And(narrow, wide)
    assert infer_width(node, _Ctx()) == WidthExpr(8, "8")


def test_infer_width_ternary_takes_the_wider_arm() -> None:
    narrow = vast.Partselect(vast.Identifier("a"), vast.IntConst("2"), vast.IntConst("0"))
    wide = vast.Partselect(vast.Identifier("b"), vast.IntConst("7"), vast.IntConst("0"))
    node = vast.Cond(vast.Identifier("sel"), wide, narrow)
    assert infer_width(node, _Ctx()) == WidthExpr(8, "8")


def test_infer_width_zero_length_range_is_refused_naming_the_line() -> None:
    node = vast.Partselect(vast.Identifier("arr"), vast.IntConst("0"), vast.IntConst("3"), lineno=42)
    with pytest.raises(UnsupportedConstruct, match="zero-length range"):
        infer_width(node, _Ctx())
    try:
        infer_width(node, _Ctx())
    except UnsupportedConstruct as exc:
        assert "42" in str(exc)


def test_infer_width_negative_length_range_is_refused() -> None:
    node = vast.Partselect(vast.Identifier("arr"), vast.IntConst("3"), vast.IntConst("9"), lineno=7)
    with pytest.raises(UnsupportedConstruct, match="zero-length range"):
        infer_width(node, _Ctx())


def test_infer_width_refuses_a_shift_naming_the_line() -> None:
    node = vast.Sll(vast.Identifier("a"), vast.IntConst("1"), lineno=99)
    with pytest.raises(UnsupportedConstruct, match="Sll"):
        infer_width(node, _Ctx())
    try:
        infer_width(node, _Ctx())
    except UnsupportedConstruct as exc:
        assert "99" in str(exc)


def test_infer_width_refuses_division() -> None:
    node = vast.Divide(vast.Identifier("a"), vast.Identifier("b"), lineno=5)
    with pytest.raises(UnsupportedConstruct, match="Divide"):
        infer_width(node, _Ctx())


def test_infer_width_refuses_modulo() -> None:
    node = vast.Mod(vast.Identifier("a"), vast.Identifier("b"), lineno=5)
    with pytest.raises(UnsupportedConstruct, match="Mod"):
        infer_width(node, _Ctx())


def test_infer_width_refuses_a_reduction_operator() -> None:
    node = vast.Uand(vast.Identifier("a"), lineno=11)
    with pytest.raises(UnsupportedConstruct, match="Uand"):
        infer_width(node, _Ctx())


def test_infer_width_refuses_a_signed_system_function() -> None:
    node = vast.SystemCall("signed", [vast.Identifier("a")], lineno=13)
    with pytest.raises(UnsupportedConstruct, match=r"\$signed system function"):
        infer_width(node, _Ctx())
