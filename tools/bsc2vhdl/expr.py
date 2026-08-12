"""Expression rendering: Verilog AST node to VHDL text.

This plan implements only what `RegN.v` needs: identifier references
through the name map, `IntConst` literals, and an `Eq` comparison. A later
plan owns the full operator set and the resize and slice policy.
"""
from __future__ import annotations

import pyverilog.vparser.ast as vast

from .errors import UnsupportedConstruct
from . import width as _width


def render_expression(node, ctx, target_width: str | None = None) -> str:
    if isinstance(node, vast.Identifier):
        return _render_identifier(node.name, ctx, target_width)
    if isinstance(node, vast.IntConst):
        return _render_int_const(node, ctx)
    if isinstance(node, vast.Eq):
        left = render_expression(node.left, ctx)
        right = render_expression(node.right, ctx)
        return f"{left} = {right}"
    raise UnsupportedConstruct(type(node).__name__, ctx.path, getattr(node, "lineno", 0))


def _render_identifier(name: str, ctx, target_width: str | None) -> str:
    if ctx.is_param(name):
        generic = ctx.generic_name[name]
        if ctx.param_kind[name] == "natural" and target_width is not None:
            return f"toSlv({generic}, {target_width})"
        return generic
    return ctx.name_for(name)


def _render_int_const(node, ctx) -> str:
    text = node.value
    literal_width = _literal_bit_width(text)
    value = _width.parse_int_literal(text)
    if literal_width == 1:
        return f"'{value}'"
    raise UnsupportedConstruct("multi-bit literal", ctx.path, getattr(node, "lineno", 0))


def _literal_bit_width(text: str) -> int | None:
    if "'" not in text:
        return None
    prefix = text.split("'", 1)[0].strip()
    return int(prefix) if prefix else None
