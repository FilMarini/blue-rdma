"""Statement rendering: Verilog AST node to VHDL text.

This plan implements blocking and nonblocking substitution, `begin`/`end`
blocks, `IfStatement`, and delegates `CaseStatement`/`CasezStatement` to
`caseconv.render_case`.

Both substitution kinds render identically here (a VHDL signal
assignment): the IR has no VHDL variables yet, and `RegN.v` only exercises
the nonblocking form inside its always block.
"""
from __future__ import annotations

import pyverilog.vparser.ast as vast

from .errors import UnsupportedConstruct
from . import expr as _expr

INDENT = "   "


def render_statement(node, ctx, indent: int) -> list[str]:
    if isinstance(node, vast.Block):
        lines: list[str] = []
        for statement in node.statements:
            lines.extend(render_statement(statement, ctx, indent))
        return lines
    if isinstance(node, vast.IfStatement):
        return _render_if(node, ctx, indent)
    if isinstance(node, (vast.BlockingSubstitution, vast.NonblockingSubstitution)):
        return _render_substitution(node, ctx, indent)
    if isinstance(node, (vast.CaseStatement, vast.CasezStatement)):
        from . import caseconv as _caseconv

        return _caseconv.render_case(node, ctx, indent)
    raise UnsupportedConstruct(type(node).__name__, ctx.path, getattr(node, "lineno", 0))


def _render_condition(node, ctx) -> str:
    # A bare single-bit identifier used as a Verilog truth test (`if (EN)`)
    # has no VHDL boolean equivalent for `std_logic`, so it is rendered as
    # an explicit `= '1'` comparison. An existing comparison (`Eq`) renders
    # through `render_expression` unchanged.
    if isinstance(node, vast.Identifier):
        return f"{_expr.render_expression(node, ctx)} = '1'"
    return _expr.render_expression(node, ctx)


def _render_if(node, ctx, indent: int) -> list[str]:
    pad = INDENT * indent
    cond = _render_condition(node.cond, ctx)
    lines = [f"{pad}if ({cond}) then"]
    lines.extend(render_statement(node.true_statement, ctx, indent + 1))

    false = node.false_statement
    if false is None:
        lines.append(f"{pad}end if;")
        return lines

    unwrapped = false.statements[0] if isinstance(false, vast.Block) and len(false.statements) == 1 else false
    if isinstance(unwrapped, vast.IfStatement):
        elsif_cond = _render_condition(unwrapped.cond, ctx)
        lines.append(f"{pad}elsif ({elsif_cond}) then")
        lines.extend(render_statement(unwrapped.true_statement, ctx, indent + 1))
        if unwrapped.false_statement is not None:
            raise UnsupportedConstruct(
                "if/elsif chain deeper than two branches", ctx.path, getattr(node, "lineno", 0)
            )
        lines.append(f"{pad}end if;")
        return lines

    lines.append(f"{pad}else")
    lines.extend(render_statement(false, ctx, indent + 1))
    lines.append(f"{pad}end if;")
    return lines


def _render_substitution(node, ctx, indent: int) -> list[str]:
    pad = INDENT * indent
    target_name = node.left.var.name
    target = ctx.name_for(target_name)
    target_width = ctx.target_width_for(target_name)
    value = _expr.render_expression(node.right.var, ctx, target_width=target_width)
    return [f"{pad}{target} <= {value};"]
