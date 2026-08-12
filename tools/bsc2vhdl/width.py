"""Width-expression evaluation and symbolic rendering.

Verilog range and replication-count text is only ever turned into a Python
integer through `evaluate_width_expr`'s whitelisted `ast` walk, a
structural copy of the surf equivalence harness's own
`evaluate_width_expr`. Nothing in this module, or anywhere else in this
package, calls `eval`, `exec`, or `ast.literal_eval` on text derived from a
`.v` file.

`infer_width` computes the self-determined bit width of an arbitrary
pyverilog expression node: a sized or unsized literal, an identifier
resolved against the declared width `ctx` already knows, a part-select or
bit-select, a concatenation, a replication, a comparison or logical
operator (always 1 bit), or a context-determined arithmetic or bitwise
operator (the maximum of its operands' self-widths). A shift, a signed or
unsigned system function, a reduction operator, a division, or a modulo is
outside the supported BSC subset and is refused by name with its file and
line, matching every other refusal in this package. A concrete range whose
computed length is zero or negative is refused the same way rather than
producing a VHDL null range that would analyze cleanly and then behave
differently from the Verilog.
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass

import pyverilog.vparser.ast as vast

from .errors import UnsupportedConstruct

_LITERAL_BASES = {"b": 2, "o": 8, "d": 10, "h": 16}

_SIMPLE_MSB_RE = re.compile(r"^\s*([A-Za-z_]\w*)\s*-\s*1\s*$")

_BINOP_TEXT = {
    ast.Add: "+",
    ast.Sub: "-",
    ast.Mult: "*",
    ast.Div: "/",
    ast.FloorDiv: "/",
}

# Node classes with a single self-determined width of 1: comparisons and
# logical (as opposed to bitwise) operators. Verilog gives every one of
# these a 1-bit result regardless of its operands' widths.
_ONE_BIT_NODE_TYPES = (
    vast.Eq,
    vast.NotEq,
    vast.Eql,
    vast.NotEql,
    vast.LessThan,
    vast.GreaterThan,
    vast.LessEq,
    vast.GreaterEq,
    vast.Land,
    vast.Lor,
    vast.Ulnot,
)

# Context-determined binary operators: both operands and the result take
# the maximum of the two operand self-widths and the context width. Verilog
# propagates width this way for the arithmetic and bitwise operators; the
# context half of that rule is applied by the renderer (`expr.py`), which
# is handed the assignment or containing operator's own target width.
_CONTEXT_DETERMINED_BINARY_TYPES = (vast.Plus, vast.Minus, vast.Times, vast.And, vast.Or, vast.Xor)

# Bitwise NOT is unary but still context-determined: its own width is its
# operand's width, propagated the same way as the binary group above.
_CONTEXT_DETERMINED_UNARY_TYPES = (vast.Unot,)


@dataclass(frozen=True)
class WidthExpr:
    """A bit width that may or may not be known as a concrete integer.

    `value` holds the concrete width when every input to its computation is
    a literal; it is `None` when the width depends on a generic and can
    only be expressed symbolically. `text` is always the VHDL text for this
    width: a plain integer string in the concrete case, or the symbolic
    generic arithmetic (`WIDTH_G`, `WIDTH_G-1`, ...) in the other. Callers
    compare `.text` to decide whether two widths are the same, since that
    comparison is correct for both cases and never folds a generic to
    whatever its default value happens to be.
    """

    value: int | None
    text: str


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


def repeated_operand(node: vast.Repeat):
    """Return the operand `{N{x}}` actually repeats.

    pyverilog always wraps the repeated value in a single-element `Concat`
    (`{N{x}}` parses as `Repeat(value=Concat([x]), times=N)`), never a bare
    `x`. Every caller that needs the repeated expression itself, not the
    wrapper, unwraps through this function rather than re-deriving the
    unwrap rule, matching the same unwrap `parser.py` and `initializers.py`
    already apply to a `Repeat` node's default-value and initial-value
    forms.
    """
    value = node.value
    if isinstance(value, vast.Concat) and len(value.list) == 1:
        return value.list[0]
    return value


def _node_to_text(node, ctx) -> str:
    """Render a width-bound or replication-count AST node as text.

    Handles exactly the same closed set of shapes `parser.py`'s own
    declaration-width-bound renderer does (`IntConst`, `Identifier`, unary
    +/-, and the four arithmetic binary operators), because a `Partselect`
    or `Repeat` count occurring inside an arbitrary expression is drawn
    from the same narrow grammar Verilog range and replication-count text
    already uses at declaration time. Anything else is refused by name.
    """
    if isinstance(node, vast.IntConst):
        return str(parse_int_literal(node.value))
    if isinstance(node, vast.Identifier):
        return node.name
    if isinstance(node, vast.Uminus):
        return f"-{_node_to_text(node.right, ctx)}"
    if isinstance(node, vast.Uplus):
        return _node_to_text(node.right, ctx)
    binop_text = {vast.Plus: "+", vast.Minus: "-", vast.Times: "*", vast.Divide: "/"}
    for cls, op in binop_text.items():
        if isinstance(node, cls):
            return f"{_node_to_text(node.left, ctx)} {op} {_node_to_text(node.right, ctx)}"
    raise UnsupportedConstruct(type(node).__name__ + " width bound", ctx.path, getattr(node, "lineno", 0))


def _width_of_range(msb_text: str, lsb_text: str, ctx, node) -> WidthExpr:
    """Compute the element count of a `[msb:lsb]` range.

    Concrete when both bounds are literal-only text; a concrete result of
    zero or negative length is refused by name rather than producing a
    VHDL null range. Falls back to `symbolic_size`'s generic arithmetic
    when either bound names a parameter `evaluate_width_expr` cannot
    resolve with no parameter bindings.
    """
    try:
        length = evaluate_width_expr(msb_text, {}) - evaluate_width_expr(lsb_text, {}) + 1
    except ValueError:
        return WidthExpr(None, symbolic_size(msb_text, lsb_text))
    if length <= 0:
        raise UnsupportedConstruct(
            f"zero-length range [{msb_text}:{lsb_text}]", ctx.path, getattr(node, "lineno", 0)
        )
    return WidthExpr(length, str(length))


def _literal_width(text: str) -> int:
    """Return a sized literal's declared width, or 32 for an unsized one."""
    if "'" not in text:
        return 32
    prefix = text.split("'", 1)[0].strip()
    return int(prefix) if prefix else 32


def _identifier_width(name: str, ctx) -> WidthExpr:
    if ctx.is_param(name):
        return WidthExpr(None, ctx.generic_name[name])
    size_text = ctx.signal_size.get(name)
    if size_text is None:
        return WidthExpr(1, "1")
    if size_text.isdigit():
        value = int(size_text)
        return WidthExpr(value, size_text)
    return WidthExpr(None, size_text)


def infer_width(node, ctx) -> WidthExpr:
    """Compute the self-determined bit width of `node`.

    Self-determined: a literal takes its declared or default size, an
    identifier takes the width `ctx` already knows for it, a part-select
    takes msb minus lsb plus one, a bit-select is 1, a concatenation is the
    sum of its operands' self-widths, a replication is its count times its
    repeated operand's self-width (kept symbolic when the count is a
    generic), and a comparison or logical operator is 1.

    Context-determined: an arithmetic or bitwise binary operator, or
    bitwise NOT, takes the maximum of its operand self-widths; the
    assignment or enclosing operator's own context width is folded in by
    `expr.py`'s renderer, which is handed that context width directly and
    is the one place resize/slice decisions are actually made. A ternary's
    width is the maximum of its two arms' self-widths for the same reason.

    Refused by name, with file and line: a shift, a signed or unsigned
    system function, a reduction operator, a division, or a modulo. None of
    these fourteen files contains one; an upstream Bluespec change that
    starts emitting one announces itself here instead of silently
    producing wrong bits.
    """
    if isinstance(node, vast.IntConst):
        width = _literal_width(node.value)
        return WidthExpr(width, str(width))
    if isinstance(node, vast.Identifier):
        return _identifier_width(node.name, ctx)
    if isinstance(node, vast.Partselect):
        msb_text = _node_to_text(node.msb, ctx)
        lsb_text = _node_to_text(node.lsb, ctx)
        return _width_of_range(msb_text, lsb_text, ctx, node)
    if isinstance(node, vast.Pointer):
        return WidthExpr(1, "1")
    if isinstance(node, vast.Concat):
        widths = [infer_width(item, ctx) for item in node.list]
        if all(w.value is not None for w in widths):
            total = sum(w.value for w in widths)
            return WidthExpr(total, str(total))
        return WidthExpr(None, " + ".join(w.text for w in widths))
    if isinstance(node, vast.Repeat):
        return _repeat_width(node, ctx)
    if isinstance(node, _ONE_BIT_NODE_TYPES):
        return WidthExpr(1, "1")
    if isinstance(node, vast.Cond):
        true_width = infer_width(node.true_value, ctx)
        false_width = infer_width(node.false_value, ctx)
        return _wider_of(true_width, false_width)
    if isinstance(node, _CONTEXT_DETERMINED_BINARY_TYPES):
        left_width = infer_width(node.left, ctx)
        right_width = infer_width(node.right, ctx)
        return _wider_of(left_width, right_width)
    if isinstance(node, _CONTEXT_DETERMINED_UNARY_TYPES):
        return infer_width(node.right, ctx)
    if isinstance(node, vast.SystemCall):
        raise UnsupportedConstruct(f"${node.syscall} system function", ctx.path, getattr(node, "lineno", 0))
    raise UnsupportedConstruct(type(node).__name__, ctx.path, getattr(node, "lineno", 0))


def _wider_of(left: WidthExpr, right: WidthExpr) -> WidthExpr:
    if left.value is not None and right.value is not None:
        value = max(left.value, right.value)
        return WidthExpr(value, str(value))
    if left.text == right.text:
        return WidthExpr(left.value, left.text)
    # Genuinely different symbolic widths with no elaboration-time value to
    # compare: keep both operands' text visible rather than silently
    # picking one, since either could turn out wider once generics bind.
    return WidthExpr(None, f"max({left.text}, {right.text})")


def _repeat_width(node: vast.Repeat, ctx) -> WidthExpr:
    operand = repeated_operand(node)
    operand_width = infer_width(operand, ctx)
    count_text = _node_to_text(node.times, ctx)
    try:
        count_value = evaluate_width_expr(count_text, {})
        count_known = True
    except ValueError:
        count_value = None
        count_known = False

    if operand_width.value == 1:
        # A single-bit repeated operand: the replication's own width is
        # exactly the count, kept symbolic (never folded to a default)
        # when the count names a generic, per TRANS-02.
        if count_known:
            return WidthExpr(count_value, str(count_value))
        return WidthExpr(None, symbolic(count_text))

    if operand_width.value is not None and count_known:
        total = count_value * operand_width.value
        return WidthExpr(total, str(total))

    raise UnsupportedConstruct(
        "replication of a non-constant-width multi-bit operand", ctx.path, getattr(node, "lineno", 0)
    )
