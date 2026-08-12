# Test methodology:
# - Sweep: `render_case` over a hand-built `casez` (zero-wildcard arm,
#   wildcard arm, arm order sensitivity) and a hand-built fully-defined
#   `case`, plus both real `casez` statements in the vendored
#   `SizedFIFO.v`.
# - Stimulus: Hand-built pyverilog AST nodes, and `SizedFIFO.v` parsed
#   directly with pyverilog (not through `parser.py`, which does not yet
#   handle a top-level continuous `assign` and is owned by a different
#   plan in this same wave).
# - Checks: Exact rendered lines; a "no `case` keyword anywhere in a
#   casez's output" scan against the rendered text, never the source; a
#   mutation check that reordering two arms changes the rendered output.
# - Timing: None. This file launches no simulator.
from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import pyverilog.vparser.ast as vast
from pyverilog.vparser.parser import parse as _pyverilog_parse

from tools.bsc2vhdl.caseconv import render_case

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

    def target_width_for(self, name: str) -> str | None:
        return self.signal_size.get(name)


def _case_arm(pattern_text: str | None, target: str, value_text: str):
    cond = None if pattern_text is None else (vast.IntConst(pattern_text),)
    statement = vast.NonblockingSubstitution(
        vast.Lvalue(vast.Identifier(target)), vast.Rvalue(vast.IntConst(value_text))
    )
    return vast.Case(cond, statement)


def _find_casez_statements(module_def):
    found = []

    def _walk(node) -> None:
        if isinstance(node, vast.CasezStatement):
            found.append(node)
        for child in node.children():
            _walk(child)

    for item in module_def.items:
        _walk(item)
    return found


def _parse_sizedfifo():
    ast_root, _directives = _pyverilog_parse(
        [str(_VENDOR_DIR / "SizedFIFO.v")], preprocess_define=[], debug=False, outputdir=tempfile.gettempdir()
    )
    module_def = [item for item in ast_root.description.definitions if isinstance(item, vast.ModuleDef)][0]
    return _find_casez_statements(module_def)


def test_render_case_casez_fully_specified_arm_compares_the_whole_selector() -> None:
    selector = vast.Concat([vast.Identifier("a"), vast.Identifier("b"), vast.Identifier("c")])
    node = vast.CasezStatement(selector, [_case_arm("3'b010", "q", "1'b1")])
    lines = render_case(node, _Ctx(), indent=0)
    assert lines[0] == 'if ((a & b & c) = "010") then'
    assert "case" not in "\n".join(lines)


def test_render_case_casez_partial_pattern_arm_uses_descending_bit_order_and_chain() -> None:
    selector = vast.Concat([vast.Identifier("a"), vast.Identifier("b"), vast.Identifier("c")])
    node = vast.CasezStatement(selector, [_case_arm("3'b0?1", "q", "1'b1")])
    lines = render_case(node, _Ctx(), indent=0)
    assert lines[0] == "if (a = '0' and c = '1') then"


def test_render_case_casez_produces_ordered_elsif_chain_with_no_case_keyword() -> None:
    selector = vast.Concat([vast.Identifier("a"), vast.Identifier("b")])
    node = vast.CasezStatement(
        selector,
        [
            _case_arm("2'b1?", "q", "1'b0"),
            _case_arm("2'b01", "q", "1'b1"),
            _case_arm("2'b00", "q", "1'b1"),
        ],
    )
    lines = render_case(node, _Ctx(), indent=0)
    keywords = [line.strip().split(" ", 1)[0] for line in lines if line.strip().startswith(("if", "elsif", "end"))]
    assert keywords == ["if", "elsif", "elsif", "end"]
    assert "case" not in "\n".join(lines)


def test_render_case_casez_arm_order_is_carried_through_not_sorted() -> None:
    selector = vast.Concat([vast.Identifier("a"), vast.Identifier("b")])
    forward = vast.CasezStatement(
        selector, [_case_arm("2'b1?", "q", "1'b0"), _case_arm("2'b01", "q", "1'b1")]
    )
    reordered = vast.CasezStatement(
        selector, [_case_arm("2'b01", "q", "1'b1"), _case_arm("2'b1?", "q", "1'b0")]
    )
    forward_lines = render_case(forward, _Ctx(), indent=0)
    reordered_lines = render_case(reordered, _Ctx(), indent=0)
    assert forward_lines != reordered_lines


def test_render_case_plain_case_emits_vhdl_case_with_when_others() -> None:
    selector = vast.Identifier("sel")
    node = vast.CaseStatement(
        selector,
        [
            _case_arm("2'b00", "q", "1'b0"),
            _case_arm("2'b01", "q", "1'b1"),
        ],
    )
    lines = render_case(node, _Ctx(), indent=0)
    assert lines[0] == "case sel is"
    assert any(line.strip() == 'when "00" =>' for line in lines)
    assert any(line.strip() == 'when "01" =>' for line in lines)
    assert lines[-2].strip() == "null;"
    assert lines[-1] == "end case;"


def test_render_case_sizedfifo_casez_statements_have_no_case_keyword_and_preserve_order() -> None:
    casez_nodes = _parse_sizedfifo()
    assert len(casez_nodes) == 2

    ctx = _Ctx()
    first_lines = render_case(casez_nodes[0], ctx, indent=0)
    second_lines = render_case(casez_nodes[1], ctx, indent=0)

    for lines, expected_arms in ((first_lines, 6), (second_lines, 4)):
        text = "\n".join(lines)
        assert "case" not in text
        # Unindented (no leading whitespace) lines are the ordered chain's
        # own top-level branches; an arm whose body contains its own
        # nested `if` (SizedFIFO.v's "ENQ only when not empty" arm does)
        # renders that nested `if` indented one level deeper, so counting
        # only column-zero lines avoids double-counting it.
        if_count = sum(1 for line in lines if line.startswith("if "))
        elsif_count = sum(1 for line in lines if line.startswith("elsif "))
        assert if_count == 1
        assert elsif_count == expected_arms - 1

    # Arm order in the rendered output matches arm order in the source: the
    # first casez's conditions, read off the `if`/`elsif` lines in order,
    # correspond to CLR, then the DEQ&&ENQ pair, then DEQ-only, DEQ-only,
    # ENQ-only-empty, ENQ-only-not-empty -- the same order as
    # SizedFIFO.v:120-162.
    branch_lines = [line for line in first_lines if line.startswith(("if ", "elsif "))]
    assert "CLR = '1'" in branch_lines[0]
    assert "ENQ = '1'" in branch_lines[-1] and "hasodata = '1'" in branch_lines[-1]
