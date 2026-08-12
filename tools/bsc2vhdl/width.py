"""Width-expression evaluation and symbolic rendering.

Verilog range and replication-count text is only ever turned into a Python
integer through `evaluate_width_expr`'s whitelisted `ast` walk, a
structural copy of the surf equivalence harness's own
`evaluate_width_expr`. Nothing in this module, or anywhere else in this
package, calls `eval`, `exec`, or `ast.literal_eval` on text derived from a
`.v` file.

`infer_width` is a documented stub: the general self-determined /
context-determined width-inference pass is owned by a later plan. This
plan's tracer only ever needs the width of an identifier or a literal, both
already known from their own declarations, so it does not call this stub.
"""
from __future__ import annotations

import ast
import re

_LITERAL_BASES = {"b": 2, "o": 8, "d": 10, "h": 16}

_SIMPLE_MSB_RE = re.compile(r"^\s*([A-Za-z_]\w*)\s*-\s*1\s*$")

_BINOP_TEXT = {
    ast.Add: "+",
    ast.Sub: "-",
    ast.Mult: "*",
    ast.Div: "/",
    ast.FloorDiv: "/",
}


def parse_int_literal(text: str) -> int:
    """Parse a Verilog integer literal such as "1", "1'b0", or "8'd633"."""
    text = text.strip()
    if "'" in text:
        _, rest = text.split("'", 1)
        base = rest[0].lower()
        digits = rest[1:]
        return int(digits, _LITERAL_BASES[base])
    return int(text)


def evaluate_width_expr(expr: str, parameters: dict[str, int]) -> int:
    """Evaluate a Verilog range or replication-count bound to an integer.

    Only integer constants, unary +/-, and the four arithmetic operators
    add/subtract/multiply/divide are accepted. Division accepts both `/`
    and `//`: Verilog's `/` on constant integers already truncates like
    Python's `//`, which is what a replication count such as
    `(width + 1)/2` needs. Bare names resolve against `parameters`. This is
    the only place Verilog range or replication-count text is ever turned
    into a number, and it must never be handed to Python's general
    string-evaluation or object-deserialization machinery.
    """

    def _eval(node: ast.AST) -> int:
        if isinstance(node, ast.Expression):
            return _eval(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, int):
            return node.value
        if isinstance(node, ast.Name):
            if node.id in parameters:
                return parameters[node.id]
            raise ValueError(f"Unresolved name in width expression {expr!r}: {node.id!r}")
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = _eval(node.operand)
            return value if isinstance(node.op, ast.UAdd) else -value
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv)):
            left = _eval(node.left)
            right = _eval(node.right)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            return left // right
        raise ValueError(f"Unsupported construct in width expression {expr!r}: {ast.dump(node)}")

    tree = ast.parse(expr, mode="eval")
    return _eval(tree)


def symbolic(expr: str) -> str:
    """Render a Verilog width-bound expression as VHDL text.

    Maps each bare parameter name to its generic name (`width` becomes
    `WIDTH_G`) and leaves the arithmetic otherwise intact, using the same
    whitelisted grammar `evaluate_width_expr` accepts. For "width - 1" this
    returns "WIDTH_G-1".
    """
    tree = ast.parse(expr, mode="eval")
    return _render(tree.body, top=True)


def symbolic_size(msb_expr: str, lsb_expr: str) -> str:
    """Render the element count of a `[msb:lsb]` range as VHDL text.

    The corpus's near-universal `[width-1:0]` idiom collapses cleanly back
    to the bare generic (`WIDTH_G`); anything else falls back to the
    literal `(msb) - (lsb) + 1` arithmetic, rendered symbolically.
    """
    if lsb_expr.strip() == "0":
        match = _SIMPLE_MSB_RE.match(msb_expr)
        if match:
            return f"{match.group(1).upper()}_G"
    return f"({symbolic(msb_expr)}) - ({symbolic(lsb_expr)}) + 1"


def _render(node: ast.AST, top: bool = False) -> str:
    if isinstance(node, ast.Constant) and isinstance(node.value, int):
        return str(node.value)
    if isinstance(node, ast.Name):
        return f"{node.id.upper()}_G"
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        value = _render(node.operand)
        return value if isinstance(node.op, ast.UAdd) else f"-{value}"
    if isinstance(node, ast.BinOp) and type(node.op) in _BINOP_TEXT:
        left = _render(node.left)
        right = _render(node.right)
        text = f"{left}{_BINOP_TEXT[type(node.op)]}{right}"
        needs_parens = not top and isinstance(node.op, (ast.Add, ast.Sub))
        return f"({text})" if needs_parens else text
    raise ValueError(f"Unsupported construct in width expression: {ast.dump(node)}")


def infer_width(node, ctx):
    """Owned by a later plan.

    Computes the self-determined or context-determined width of an
    arbitrary expression node. Not needed by the RegN tracer, which only
    ever touches identifier and literal widths already known from their own
    declarations.
    """
    raise NotImplementedError("infer_width is implemented by a later plan")
