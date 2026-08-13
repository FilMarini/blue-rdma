# Test methodology:
# - Sweep: Every explicit-resize/explicit-slice rule `render_expression`
#   implements (equal width emits nothing, narrower emits one `resize`,
#   wider emits one explicit `downto` slice), the operator mappings
#   (equality, relational, logical, bitwise, arithmetic, ternary,
#   replication, part-select, bit-select), and the one real hard site the
#   corpus contains: `FIFO2.v`'s masked-OR data path.
# - Stimulus: Hand-built pyverilog AST nodes plus a minimal stand-in
#   context, and the real vendored `FIFO2.v` fixture parsed directly with
#   pyverilog (not through `parser.py`, which does not yet handle a
#   top-level continuous `assign` and is owned by a different plan in this
#   same wave).
# - Checks: Exact rendered text, and a positive/negative substring check
#   for `resize`/`downto` on the equal-width case.
# - Timing: None. This file launches no simulator.
from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import pyverilog.vparser.ast as vast
from pyverilog.vparser.parser import parse as _pyverilog_parse

from tools.bsc2vhdl.expr import render_expression

_VENDOR_DIR = Path(__file__).resolve().parent / "vendor"


@dataclass
class _Ctx:
    path: Path = field(default_factory=lambda: Path("synthetic.v"))
    signal_size: dict = field(default_factory=dict)
    generic_name: dict = field(default_factory=dict)
    param_kind: dict = field(default_factory=dict)
    param_names: set = field(default_factory=set)

    def is_param(self, name: str) -> bool:
        return name in self.param_names

    def name_for(self, name: str) -> str:
        return name


def _vector_ctx(**signal_size: str) -> _Ctx:
    return _Ctx(signal_size=dict(signal_size))


def _parse_raw(path: Path):
    ast_root, _directives = _pyverilog_parse(
        [str(path)], preprocess_define=[], debug=False, outputdir=tempfile.gettempdir()
    )
    return [item for item in ast_root.description.definitions if isinstance(item, vast.ModuleDef)][0]


def _find_nonblocking_assign(module_def, target_name: str):
    matches = []

    def _walk(node) -> None:
        if isinstance(node, vast.NonblockingSubstitution) and getattr(node.left.var, "name", None) == target_name:
            matches.append(node)
        for child in node.children():
            _walk(child)

    for item in module_def.items:
        _walk(item)
    return matches[0]


def test_render_expression_equal_width_emits_bare_operand() -> None:
    ctx = _vector_ctx(D_IN="WIDTH_G")
    text = render_expression(vast.Identifier("D_IN"), ctx, target_width="WIDTH_G")
    assert text == "D_IN"
    assert "resize" not in text
    assert "downto" not in text


def test_render_expression_narrower_operand_emits_one_resize() -> None:
    ctx = _vector_ctx(SMALL="4")
    text = render_expression(vast.Identifier("SMALL"), ctx, target_width="8")
    assert text == "resize(SMALL, 8)"
    assert text.count("resize(") == 1


def test_render_expression_wider_operand_emits_one_explicit_slice() -> None:
    ctx = _vector_ctx(BIG="16")
    text = render_expression(vast.Identifier("BIG"), ctx, target_width="8")
    assert text == "BIG(8-1 downto 0)"
    assert text.count("downto") == 1
    assert "resize" not in text


def test_render_expression_replication_of_a_parameter_count_uses_slv_all() -> None:
    ctx = _Ctx(generic_name={"width": "WIDTH_G"}, param_names={"width"})
    node = vast.Repeat(vast.Concat([vast.Identifier("d0di")]), vast.Identifier("width"))
    text = render_expression(node, ctx, target_width="WIDTH_G")
    assert text == "slvAll(WIDTH_G, d0di)"


def test_render_expression_equality_produces_a_bare_boolean_by_default() -> None:
    ctx = _Ctx()
    node = vast.Eq(vast.Identifier("RST"), vast.IntConst("1'b0"))
    text = render_expression(node, ctx, target_width=None)
    assert text == "RST = '0'"


def test_render_expression_equality_converts_to_sl_for_a_vector_context() -> None:
    ctx = _Ctx()
    node = vast.Eq(vast.Identifier("a"), vast.Identifier("b"))
    text = render_expression(node, ctx, target_width="1")
    assert text == "toSl(a = b)"


def test_render_expression_relational_uses_unsigned_conversions() -> None:
    ctx = _vector_ctx(a="WIDTH_G", b="WIDTH_G")
    node = vast.LessThan(vast.Identifier("a"), vast.Identifier("b"))
    text = render_expression(node, ctx, target_width=None)
    assert text == "unsigned(a) < unsigned(b)"


def test_render_expression_ternary_renders_both_arms_at_the_same_width() -> None:
    ctx = _vector_ctx(DATA_C="WIDTH_G", q_state="WIDTH_G")
    node = vast.Cond(vast.Identifier("SETC"), vast.Identifier("DATA_C"), vast.Identifier("q_state"))
    text = render_expression(node, ctx, target_width="WIDTH_G")
    assert text == "ite((SETC = '1'), DATA_C, q_state)"


def test_render_expression_bitwise_and_or_chain_parenthesizes_mixed_operators() -> None:
    ctx = _vector_ctx(a="WIDTH_G", b="WIDTH_G", c="WIDTH_G", d="WIDTH_G")
    node = vast.Or(
        vast.And(vast.Identifier("a"), vast.Identifier("b")),
        vast.And(vast.Identifier("c"), vast.Identifier("d")),
    )
    text = render_expression(node, ctx, target_width="WIDTH_G")
    assert text == "(a and b) or (c and d)"
    assert text.count(" or ") == 1


def test_render_expression_arithmetic_chain_uses_unsigned_and_wraps_in_slv() -> None:
    ctx = _vector_ctx(a="WIDTH_G", b="WIDTH_G", c="WIDTH_G")
    node = vast.Plus(vast.Plus(vast.Identifier("a"), vast.Identifier("b")), vast.Identifier("c"))
    text = render_expression(node, ctx, target_width="WIDTH_G")
    assert text == "slv(unsigned(a) + unsigned(b) + unsigned(c))"


def test_render_expression_partselect_renders_a_downto_slice() -> None:
    ctx = _Ctx()
    msb = vast.Minus(vast.Identifier("p3cntr_width"), vast.IntConst("1"))
    node = vast.Partselect(vast.Identifier("p2depth2"), msb, vast.IntConst("0"))
    text = render_expression(node, ctx, target_width=None)
    assert text == "p2depth2(P3CNTR_WIDTH_G-1 downto 0)"


def test_render_expression_narrow_shift_amount_uses_bare_to_integer() -> None:
    # A shift-amount operand at or under _SHIFT_AMOUNT_SAFE_BITS keeps the
    # original, unguarded rendering: mkQP.v's own ten shift usages (all a
    # handful of bits wide) must never see the saturating construct added
    # for mkTransportLayer.v's own oversized register.
    ctx = _vector_ctx(WIDE_LHS="32", NARROW_AMOUNT="5")
    node = vast.Sll(vast.Identifier("WIDE_LHS"), vast.Identifier("NARROW_AMOUNT"))
    text = render_expression(node, ctx, target_width=None)
    assert text == "slv(shift_left(unsigned(WIDE_LHS), to_integer(unsigned(NARROW_AMOUNT))))"
    assert "ite(" not in text


def test_render_expression_wide_shift_amount_saturates_instead_of_crashing() -> None:
    # mkTransportLayer.v's own headerInvalidFragBitNumReg (513 bits, shifted
    # by directly with no slicing in the source Verilog): a bare to_integer
    # on the full width overflows NATURAL inside numeric_std's own
    # TO_INTEGER at GHDL runtime the instant enough high bits are set (the
    # register's simulation-only alternating power-on pattern reaches this
    # unconditionally). The saturating form instead checks only the bits
    # above _SHIFT_AMOUNT_SAFE_BITS for exact zero and falls back to the
    # shift's own left-operand width (self_width) when any of them are set,
    # matching Verilog's own all-zero result for an oversized shift amount.
    ctx = _vector_ctx(WIDE_LHS="32", WIDE_AMOUNT="513")
    node = vast.Sll(vast.Identifier("WIDE_LHS"), vast.Identifier("WIDE_AMOUNT"))
    text = render_expression(node, ctx, target_width=None)
    assert text == (
        "slv(shift_left(unsigned(WIDE_LHS), "
        "ite(unsigned(WIDE_AMOUNT(513 - 1 downto 30)) /= 0, 32, "
        "to_integer(unsigned(WIDE_AMOUNT(30 - 1 downto 0))))))"
    )
    assert "bound check" not in text  # documentation only; the real proof is GHDL not crashing


def test_render_expression_wide_shift_amount_non_identifier_stays_on_original_path() -> None:
    # A wide shift-amount operand that is not a bare identifier (never seen
    # in the corpus) cannot be sliced by name, so it is left on the
    # original, unguarded to_integer rendering rather than attempting an
    # unsound transform.
    ctx = _vector_ctx(WIDE_LHS="32", WIDE_A="257", WIDE_B="257")
    node = vast.Sll(vast.Identifier("WIDE_LHS"), vast.Plus(vast.Identifier("WIDE_A"), vast.Identifier("WIDE_B")))
    text = render_expression(node, ctx, target_width=None)
    assert "ite(" not in text
    assert "to_integer(unsigned(" in text


def test_render_expression_fifo2_masked_or_datapath() -> None:
    module_def = _parse_raw(_VENDOR_DIR / "FIFO2.v")
    assign = _find_nonblocking_assign(module_def, "data0_reg")
    ctx = _vector_ctx(D_IN="WIDTH_G", data0_reg="WIDTH_G", data1_reg="WIDTH_G")
    ctx.param_names.add("width")
    ctx.generic_name["width"] = "WIDTH_G"

    text = render_expression(assign.right.var, ctx, target_width="WIDTH_G")

    assert text.count("slvAll(") == 3
    assert text.count(" or ") == 2
    assert text == (
        "(slvAll(WIDTH_G, d0di) and D_IN) or "
        "(slvAll(WIDTH_G, d0d1) and data1_reg) or "
        "(slvAll(WIDTH_G, d0h) and data0_reg)"
    )
