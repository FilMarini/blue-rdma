"""`case` and `casez` to VHDL.

A `casez` always becomes an ordered `if`/`elsif` chain in source order,
never a VHDL `case`: the corpus's wildcard patterns overlap (`SizedFIFO.v`'s
own two `casez` statements resolve by first match), and an unordered `case`
cannot express that. A plain `case` whose arms are all fully defined
literals becomes a VHDL `case` with a `when others` arm; if any arm's
literal carries a don't-care bit, it falls through to the same
ordered-chain rendering a `casez` uses, so a `case` and a `casez` can never
disagree about what a don't-care bit means. Both read every pattern through
`dontcare.parse_sized_literal`, the one function that resolves a
`casez`/`case` wildcard bit anywhere in this package.
"""
from __future__ import annotations

import pyverilog.vparser.ast as vast

from .dontcare import parse_sized_literal
from .errors import UnsupportedConstruct
from . import expr as _expr
from . import width as _width

INDENT = "   "


def render_case(node, ctx, indent: int) -> list[str]:
    if isinstance(node, vast.CasezStatement):
        return _render_ordered_chain(node, ctx, indent)
    if isinstance(node, vast.CaseStatement):
        if _requires_ordered_chain(node):
            return _render_ordered_chain(node, ctx, indent)
        return _render_plain_case(node, ctx, indent)
    raise UnsupportedConstruct(type(node).__name__, ctx.path, getattr(node, "lineno", 0))


def _requires_ordered_chain(node: vast.CaseStatement) -> bool:
    for arm in node.caselist:
        if not arm.cond:
            continue
        for pattern in arm.cond:
            if not isinstance(pattern, vast.IntConst):
                return True
            literal = parse_sized_literal(pattern.value)
            if literal.care_mask != (1 << literal.width) - 1:
                return True
    return False


def _render_body(statement, ctx, indent: int) -> list[str]:
    # Deferred import: `stmt.py` delegates `CaseStatement`/`CasezStatement`
    # to this module, so importing `stmt` at module load time would be
    # circular. By the time this function actually runs, both modules are
    # fully loaded.
    from . import stmt as _stmt

    return _stmt.render_statement(statement, ctx, indent)


def _selector_operand(comp_node, bit_index: int, ctx) -> tuple[str, int | None]:
    """Return the rendered text (and, if multi-bit, a local bit index) of
    whichever piece of `comp_node` carries bit `bit_index` (0 = least
    significant). For a bare (non-`Concat`) selector this is the whole
    selector indexed directly."""
    if not isinstance(comp_node, vast.Concat):
        text = _expr.render_expression(comp_node, ctx, target_width=None)
        return text, bit_index
    offset = 0
    for operand in reversed(comp_node.list):
        operand_width = _width.infer_width(operand, ctx)
        width = operand_width.value if operand_width.value is not None else 1
        if offset <= bit_index < offset + width:
            local_index = bit_index - offset
            text = _expr.render_expression(operand, ctx, target_width=None)
            return text, (None if width == 1 else local_index)
        offset += width
    raise UnsupportedConstruct(
        "casez selector bit index out of range", ctx.path, getattr(comp_node, "lineno", 0)
    )


def _bit_condition(comp_node, bit_index: int, expected_bit: int, ctx) -> str:
    text, local_index = _selector_operand(comp_node, bit_index, ctx)
    literal = "'1'" if expected_bit else "'0'"
    target = text if local_index is None else f"{text}({local_index})"
    return f"{target} = {literal}"


def _whole_selector_condition(comp_node, literal, ctx) -> str:
    selector_text = _expr.render_expression(comp_node, ctx, target_width=None)
    bits = format(literal.value, f"0{literal.width}b")
    return f'{selector_text} = "{bits}"'


def _pattern_condition(comp_node, pattern_text: str, ctx) -> str:
    literal = parse_sized_literal(pattern_text)
    full_mask = (1 << literal.width) - 1
    if literal.care_mask == full_mask:
        return _whole_selector_condition(comp_node, literal, ctx)
    terms = []
    for bit_index in range(literal.width - 1, -1, -1):
        if not (literal.care_mask >> bit_index) & 1:
            continue
        expected_bit = (literal.value >> bit_index) & 1
        terms.append(_bit_condition(comp_node, bit_index, expected_bit, ctx))
    return " and ".join(terms)


def _arm_condition(comp_node, arm, ctx) -> str | None:
    patterns = arm.cond
    if not patterns:
        return None
    parts = [_pattern_condition(comp_node, pattern.value, ctx) for pattern in patterns]
    if len(parts) == 1:
        return parts[0]
    return " or ".join(f"({part})" for part in parts)


def _render_ordered_chain(node, ctx, indent: int) -> list[str]:
    pad = INDENT * indent
    comp_node = node.comp
    conditions = [(_arm_condition(comp_node, arm, ctx), arm) for arm in node.caselist]

    lines: list[str] = []
    wrote_branch = False
    default_arm = None
    for condition, arm in conditions:
        if condition is None:
            default_arm = arm
            continue
        keyword = "elsif" if wrote_branch else "if"
        lines.append(f"{pad}{keyword} ({condition}) then")
        lines.extend(_render_body(arm.statement, ctx, indent + 1))
        wrote_branch = True

    if not wrote_branch:
        # Only a default arm exists (not present anywhere in this corpus,
        # but not refused either): its body is unconditional.
        return _render_body(default_arm.statement, ctx, indent) if default_arm is not None else []

    if default_arm is not None:
        lines.append(f"{pad}else")
        lines.extend(_render_body(default_arm.statement, ctx, indent + 1))
    lines.append(f"{pad}end if;")
    return lines


def _render_plain_case(node, ctx, indent: int) -> list[str]:
    pad = INDENT * indent
    comp_node = node.comp
    selector_text = _expr.render_expression(comp_node, ctx, target_width=None)
    lines = [f"{pad}case {selector_text} is"]

    default_arm = None
    for arm in node.caselist:
        if not arm.cond:
            default_arm = arm
            continue
        choices = []
        for pattern in arm.cond:
            literal = parse_sized_literal(pattern.value)
            bits = format(literal.value, f"0{literal.width}b")
            choices.append(f'"{bits}"')
        lines.append(f"{pad}{INDENT}when {' | '.join(choices)} =>")
        lines.extend(_render_body(arm.statement, ctx, indent + 2))

    lines.append(f"{pad}{INDENT}when others =>")
    if default_arm is not None:
        lines.extend(_render_body(default_arm.statement, ctx, indent + 2))
    else:
        lines.append(f"{pad}{INDENT * 2}null;")
    lines.append(f"{pad}end case;")
    return lines
