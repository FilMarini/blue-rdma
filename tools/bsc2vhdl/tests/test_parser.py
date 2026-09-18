# Test methodology:
# - Sweep: The subset of pyverilog-visible constructs actually present in
#   the vendored `RegN.v`: two parameters (one plain, one a zero-valued
#   replication default), five ports in header order, and one always
#   block. `evaluate_width_expr` is swept over the two arithmetic shapes
#   the corpus's width bounds and replication counts actually use.
# - Stimulus: The vendored `RegN.v` fixture (hermetic: no BSC install, no
#   surf checkout), plus hand-built width-expression strings and parameter
#   dictionaries for the `evaluate_width_expr` cases.
# - Checks: Every rejection case asserts on its message via `match=`.
# - Timing: None. This file launches no simulator.
from __future__ import annotations

from pathlib import Path

import pytest

from tools.bsc2vhdl.parser import parse_module
from tools.bsc2vhdl.width import evaluate_width_expr


def test_parse_module_regn(vendor_dir: Path) -> None:
    module_ir = parse_module(vendor_dir / "RegN.v")

    assert module_ir.name == "RegN"
    assert [param.name for param in module_ir.params] == ["width", "init"]
    assert module_ir.params[0].default_value == 1
    assert module_ir.params[1].default_value == 0

    assert [port.name for port in module_ir.ports] == ["CLK", "RST", "Q_OUT", "D_IN", "EN"]
    assert [port.direction for port in module_ir.ports] == ["in", "in", "out", "in", "in"]

    assert len(module_ir.always_blocks) == 1
    assert len(module_ir.initials) == 1


def test_evaluate_width_expr_subtraction() -> None:
    assert evaluate_width_expr("width - 1", {"width": 8}) == 7


def test_evaluate_width_expr_floor_division() -> None:
    assert evaluate_width_expr("(width + 1)/2", {"width": 7}) == 4


def test_evaluate_width_expr_rejects_call_expression() -> None:
    with pytest.raises(ValueError, match="Unsupported construct"):
        evaluate_width_expr("__import__('os')", {})


def test_evaluate_width_expr_rejects_unresolved_name() -> None:
    with pytest.raises(ValueError, match="Unresolved name"):
        evaluate_width_expr("depth", {"width": 8})
