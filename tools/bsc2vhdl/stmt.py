"""Statement rendering: Verilog AST node to VHDL text.

Implements blocking and nonblocking substitution, `begin`/`end` blocks, an
`IfStatement`/`elsif` chain of arbitrary depth, and delegates
`CaseStatement`/`CasezStatement` to `caseconv.render_case`.

Both substitution kinds render identically here (a VHDL signal
assignment): the IR has no VHDL variables yet.

A substitution whose target is a `Pointer` (`RAM[ADDRA] <= DIA;`,
`arr[tail] <= D_IN;`) writes one element of a memory array rather than a
plain signal: the target renders as `<array>(to_integer(unsigned(<index>)))`,
the same index conversion `expr.py`'s own memory-element read path uses,
and the assigned value's target width comes from the array's own element
width (`ctx.target_width_for` on the array's name already holds that,
since `emit.py` populates it identically for a memory and a plain vector
signal).
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
    """Render an `if`/`elsif`/.../`else` chain of arbitrary depth.

    Verilog nests `else if` as an `IfStatement` inside the enclosing
    `IfStatement`'s own `false_statement`; this walks that chain with an
    explicit loop rather than one level of recursion, since `FIFO2.v`'s and
    `FIFO20.v`'s own status state machines are each a three-arm chain
    (clear, enqueue-only, dequeue-only) with no final `else` at all -- the
    fourth case (a simultaneous enqueue and dequeue) falls through
    unchanged, which is the original's own documented behavior, not a case
    this renderer needs to add a branch for.
    """
    pad = INDENT * indent
    cond = _render_condition(node.cond, ctx)
    lines = [f"{pad}if ({cond}) then"]
    lines.extend(render_statement(node.true_statement, ctx, indent + 1))

    false = node.false_statement
    while false is not None:
        unwrapped = false.statements[0] if isinstance(false, vast.Block) and len(false.statements) == 1 else false
        if not isinstance(unwrapped, vast.IfStatement):
            lines.append(f"{pad}else")
            lines.extend(render_statement(false, ctx, indent + 1))
            false = None
            break
        elsif_cond = _render_condition(unwrapped.cond, ctx)
        lines.append(f"{pad}elsif ({elsif_cond}) then")
        lines.extend(render_statement(unwrapped.true_statement, ctx, indent + 1))
        false = unwrapped.false_statement

    lines.append(f"{pad}end if;")
    return lines


def _render_substitution(node, ctx, indent: int) -> list[str]:
    pad = INDENT * indent
    target_var = node.left.var
    if isinstance(target_var, vast.Pointer):
        return _render_memory_write(target_var, node.right.var, ctx, pad)
    target_name = target_var.name
    target = ctx.name_for(target_name)
    target_width = ctx.target_width_for(target_name)
    value = _expr.render_expression(node.right.var, ctx, target_width=target_width)
    return [f"{pad}{target} <= {value};"]


def _render_memory_write(pointer_node: vast.Pointer, rhs, ctx, pad: str) -> list[str]:
    base_var = pointer_node.var
    if not isinstance(base_var, vast.Identifier):
        raise UnsupportedConstruct(
            "memory write with a non-identifier base", ctx.path, getattr(pointer_node, "lineno", 0)
        )
    base_name = base_var.name
    base = ctx.name_for(base_name)
    index_text = _expr.render_expression(pointer_node.ptr, ctx, target_width=None)
    target = f"{base}(to_integer(unsigned({index_text})))"
    target_width = ctx.target_width_for(base_name)
    value = _expr.render_expression(rhs, ctx, target_width=target_width)
    # A memory written from more than one process is emitted as a shared
    # variable, not a signal (see emit.py's _memories_with_multiple_writers):
    # two processes each driving one signal is a multiple-driver conflict
    # that resolves to 'X' wherever the two drivers' views of an element
    # disagree, while an assignment to a shared variable takes effect
    # immediately with nothing to resolve. The operator is the only
    # difference: `:=` for a variable, `<=` for a signal.
    operator = ":=" if ctx.is_shared_memory(base_name) else "<="
    return [f"{pad}{target} {operator} {value};"]
