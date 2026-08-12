"""Identifies simulation-only module items by abstract-syntax-tree shape.

`// synopsys translate_off` is a plain Verilog comment; pyverilog's parser
sees straight through it to the real AST nodes regardless, so detection
here never inspects comment text. This plan implements only the one shape
`RegN.v` needs: an `Initial` node, whose content `initializers.py` consumes
as a signal default rather than emitting as behavior. A later plan owns
`$display` always-blocks, `#delay`, and `task`.
"""
from __future__ import annotations

import pyverilog.vparser.ast as vast


def is_simulation_only(node) -> bool:
    return isinstance(node, vast.Initial)
