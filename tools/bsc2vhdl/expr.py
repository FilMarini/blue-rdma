"""Expression rendering: Verilog AST node to VHDL text.

One rule governs every width change: when a rendered subexpression's width
already equals the width its context requires, the bare text is emitted
with no wrapper; when it is narrower, it is wrapped in exactly one
`resize(<expr>, <target>)` call; when it is wider, it is wrapped in exactly
one explicit `<expr>(<target>-1 downto 0)` slice. `render_expression` never
emits a resize whose source and target widths are equal and never emits
both a resize and a slice on the same subexpression, both proven by test.

Every non-atomic subexpression is parenthesized when it appears as an
operand of a different operator, because VHDL's logical operators (`and`,
`or`, `xor`) have no relative precedence and an unparenthesized mix does
not analyze; operands of the same operator in a left-associative chain
(`a and b and c`) are flattened rather than nested, matching the shape
`FIFO2.vhd`'s own hand-written masked-OR datapath uses.
"""
from __future__ import annotations

import pyverilog.vparser.ast as vast

from .errors import UnsupportedConstruct
from . import width as _width

_LOGICAL_OP_TYPES = (vast.And, vast.Or, vast.Xor, vast.Land, vast.Lor)

_EQUALITY_OPS = {
    vast.Eq: "=",
    vast.NotEq: "/=",
    vast.Eql: "=",
    vast.NotEql: "/=",
}

_RELATIONAL_OPS = {
    vast.LessThan: "<",
    vast.GreaterThan: ">",
    vast.LessEq: "<=",
    vast.GreaterEq: ">=",
}

_BITWISE_OPS = {vast.And: "and", vast.Or: "or", vast.Xor: "xor"}

_SHIFT_OPS = {vast.Sll: "shift_left", vast.Srl: "shift_right"}

def _qualify_for_cast(node, text: str) -> str:
    """Pin an ambiguous subexpression's type before it reaches a type
    conversion (`unsigned(...)`/`signed(...)`) or an equality against
    another equally ambiguous operand.

    A bare literal, and a `resize(...)` call wrapping one (`_fit`'s own
    resize wrap never itself qualifies: it has no visibility into whatever
    the caller does with its return value), render as VHDL text
    simultaneously compatible with more than one of
    `slv`/`unresolved_unsigned`/`unresolved_signed`: `std_logic_1164` and
    `numeric_std` both provide `&`/literal-typing/`resize` rules reaching
    all three, so GHDL's overload resolution cannot pick one on its own
    once the surrounding context does not concretely anchor it either.
    `toSlv(...)`/`slvAll(...)` are each a single, already-`slv`-typed
    function call -- `_render_int_const`'s `toSlv(...)` branch in
    particular never reaches `_fit` at all -- so neither is ever
    qualified, on pain of a redundant qualifier changing this module's own
    already-committed output text for no analysis-relevant reason. A
    genuine `&`-chain (a `Concat` of more than one piece; `_render_concat`
    itself returns its lone piece's own text unchanged, with no wrapping
    parens at all, when there is only one) carries the identical
    ambiguity. A name, a bit-select, or any other function call already
    carries a fixed type from its own declaration or return type and is
    never qualified.
    """
    if isinstance(node, vast.IntConst):
        if text.startswith("toSlv("):
            return text
        if text.startswith("'"):
            return f"sl'({text})"
        return f"slv'({text})"
    if isinstance(node, vast.Concat) and len(node.list) > 1:
        return f"slv'({text})"
    return text


def render_expression(node, ctx, target_width: str | None = None) -> str:
    if isinstance(node, vast.Identifier):
        return _render_identifier(node, ctx, target_width)
    if isinstance(node, vast.IntConst):
        return _render_int_const(node, ctx, target_width)
    if isinstance(node, tuple(_EQUALITY_OPS)):
        return _render_equality(node, ctx, target_width)
    if isinstance(node, tuple(_RELATIONAL_OPS)):
        return _render_relational(node, ctx, target_width)
    if isinstance(node, (vast.Land, vast.Lor)):
        return _render_logical_binary(node, ctx, target_width)
    if isinstance(node, vast.Ulnot):
        return _render_logical_not(node, ctx, target_width)
    if isinstance(node, tuple(_BITWISE_OPS)):
        return _render_bitwise_binary(node, ctx, target_width)
    if isinstance(node, vast.Unot):
        return _render_bitwise_not(node, ctx, target_width)
    if isinstance(node, (vast.Plus, vast.Minus)):
        return _render_arith_chain(node, ctx, target_width)
    if isinstance(node, tuple(_SHIFT_OPS)):
        return _render_shift(node, ctx, target_width)
    if isinstance(node, vast.Cond):
        return _render_cond(node, ctx, target_width)
    if isinstance(node, vast.Concat):
        return _render_concat(node, ctx, target_width)
    if isinstance(node, vast.Repeat):
        return _render_repeat(node, ctx, target_width)
    if isinstance(node, vast.Partselect):
        return _render_partselect(node, ctx, target_width)
    if isinstance(node, vast.Pointer):
        return _render_pointer(node, ctx, target_width)
    raise UnsupportedConstruct(type(node).__name__, ctx.path, getattr(node, "lineno", 0))


def _fit(text: str, self_width: _width.WidthExpr, target_width: str | None, node, ctx) -> str:
    # `StdRtlPkg.resize`, `numeric_std.resize` (twice, `unresolved_unsigned`
    # and `unresolved_signed`), a bare multi-bit string literal, and a
    # `&`-chain are all mutually compatible, ambiguously, the moment some
    # *outer* caller wraps this call's own result in
    # `unsigned(...)`/`signed(...)` or compares it against an equally
    # ambiguous operand. This function has no visibility into whatever the
    # caller does with its return value, so it never qualifies here;
    # `_qualify_for_cast` does that at each of the handful of call sites
    # that actually need it, wrapping this function's *entire* output
    # (bare or already `resize(...)`-wrapped, either way) rather than
    # reaching inside it.
    if target_width is None or self_width.text == target_width:
        return text
    if self_width.value is not None and target_width.isdigit():
        target_value = int(target_width)
        if self_width.value < target_value:
            return f"resize({text}, {target_width})"
        if self_width.value > target_value:
            return f"{text}({target_width}-1 downto 0)"
        return text
    # Two symbolic widths whose text differs: there is no static way to
    # prove they are equal at elaboration time, so the conservative choice
    # is an explicit resize rather than silently assuming equality.
    return f"resize({text}, {target_width})"


def _render_identifier(node: vast.Identifier, ctx, target_width: str | None) -> str:
    name = node.name
    if ctx.is_param(name):
        generic = ctx.generic_name[name]
        if ctx.param_kind[name] == "natural" and target_width is not None:
            return f"toSlv({generic}, {target_width})"
        return generic
    text = ctx.name_for(name)
    self_width = _width.infer_width(node, ctx)
    return _fit(text, self_width, target_width, node, ctx)


def _render_int_const(node: vast.IntConst, ctx, target_width: str | None) -> str:
    text = node.value
    value = _width.parse_int_literal(text)
    self_width = _width.infer_width(node, ctx)
    if self_width.value == 1 and target_width not in (None, "1"):
        # A 1-bit literal (`1'b1`, the `+ 1` in `tail + 1'b1`, ...) widened
        # by a vector context has no `_fit`-through-`resize` path: `resize`
        # is defined only for `unsigned`/`signed`, and a scalar `'1'`
        # character literal is not array-typed at all, so wrapping it in
        # `resize(...)` is a type error regardless of context. `toSlv` is
        # the same elaboration-time value-to-vector conversion this
        # codebase already uses for a "natural"-kind parameter in a vector
        # context; a literal widened by arithmetic context is the same
        # shape of problem.
        return f"toSlv({value}, {target_width})"
    if self_width.value == 1:
        core = f"'{value}'"
    else:
        core = f'"{format(value, "0{}b".format(self_width.value))}"'
    return _fit(core, self_width, target_width, node, ctx)


def _comparison_width(left_node, right_node, ctx) -> str | None:
    combined = _width._wider_of(_width.infer_width(left_node, ctx), _width.infer_width(right_node, ctx))
    return combined.text


def _is_ambiguous_operand(node, text: str) -> bool:
    """True exactly when `node`'s own rendering (`text`) is a bare literal,
    a `resize(...)` call wrapping one, or a genuine `&`-chain -- the shapes
    `_qualify_for_cast` pins -- never merely because `node` is an
    `IntConst`/`Concat` node whose own rendering already resolved to an
    unambiguous function call (`toSlv(...)`, `slvAll(...)`, or a
    single-piece `Concat`'s bare passthrough)."""
    if isinstance(node, vast.IntConst):
        return not text.startswith("toSlv(")
    if isinstance(node, vast.Concat):
        return len(node.list) > 1
    return False


def _render_equality(node, ctx, target_width: str | None) -> str:
    op_text = _EQUALITY_OPS[type(node)]
    compared_width = _comparison_width(node.left, node.right, ctx)
    left = render_expression(node.left, ctx, target_width=compared_width)
    right = render_expression(node.right, ctx, target_width=compared_width)
    if _is_ambiguous_operand(node.left, left) and _is_ambiguous_operand(node.right, right):
        # Neither side anchors the comparison's type on its own (both are
        # built from a literal/`&`-chain shape, `mkQP.v`'s
        # `(sig & "0000000" & sig) = "0000...0001"` among them), so `=`'s
        # `slv`/`unresolved_unsigned`/`unresolved_signed` overloads are all
        # simultaneously satisfiable without an explicit qualifier.
        left = _qualify_for_cast(node.left, left)
        right = _qualify_for_cast(node.right, right)
    core = f"{left} {op_text} {right}"
    if target_width is None:
        return core
    return f"toSl({core})"


def _render_relational(node, ctx, target_width: str | None) -> str:
    op_text = _RELATIONAL_OPS[type(node)]
    compared_width = _comparison_width(node.left, node.right, ctx)
    left = render_expression(node.left, ctx, target_width=compared_width)
    right = render_expression(node.right, ctx, target_width=compared_width)
    left = _qualify_for_cast(node.left, left)
    right = _qualify_for_cast(node.right, right)
    core = f"unsigned({left}) {op_text} unsigned({right})"
    if target_width is None:
        return core
    return f"toSl({core})"


def _render_logical_binary(node, ctx, target_width: str | None) -> str:
    op_text = "and" if isinstance(node, vast.Land) else "or"
    left = render_expression(node.left, ctx, target_width="1")
    right = render_expression(node.right, ctx, target_width="1")
    core = f"({left} {op_text} {right})"
    return _fit(core, _width.WidthExpr(1, "1"), target_width, node, ctx)


def _render_logical_not(node: vast.Ulnot, ctx, target_width: str | None) -> str:
    operand = render_expression(node.right, ctx, target_width="1")
    core = f"(not {operand})"
    return _fit(core, _width.WidthExpr(1, "1"), target_width, node, ctx)


def _flatten_same_op(node):
    op_type = type(node)
    terms: list = []

    def _walk(inner) -> None:
        if type(inner) is op_type:
            _walk(inner.left)
            terms.append(inner.right)
        else:
            terms.append(inner)

    _walk(node)
    return terms


def _render_bitwise_binary(node, ctx, target_width: str | None) -> str:
    op_type = type(node)
    op_text = _BITWISE_OPS[op_type]
    terms = _flatten_same_op(node)
    widths = [_width.infer_width(term, ctx) for term in terms]
    width = _effective_width(target_width, *widths)

    rendered: list[str] = []
    for term in terms:
        text = render_expression(term, ctx, target_width=width)
        if isinstance(term, _LOGICAL_OP_TYPES) and type(term) is not op_type:
            text = f"({text})"
        rendered.append(text)
    return f" {op_text} ".join(rendered)


def _render_bitwise_not(node: vast.Unot, ctx, target_width: str | None) -> str:
    operand_width = _width.infer_width(node.right, ctx)
    width = _effective_width(target_width, operand_width)
    operand = render_expression(node.right, ctx, target_width=width)
    if isinstance(node.right, _LOGICAL_OP_TYPES):
        operand = f"({operand})"
    return f"(not {operand})"


def _effective_width(target_width: str | None, *self_widths: "_width.WidthExpr") -> str | None:
    if target_width is not None:
        return target_width
    concrete = [w.value for w in self_widths if w.value is not None]
    if self_widths and len(concrete) == len(self_widths):
        return str(max(concrete))
    for w in self_widths:
        if w.text:
            return w.text
    return None


def _flatten_arith_chain(node):
    if isinstance(node, (vast.Plus, vast.Minus)):
        terms, ops = _flatten_arith_chain(node.left)
        op = "+" if isinstance(node, vast.Plus) else "-"
        return terms + [node.right], ops + [op]
    return [node], []


def _render_arith_chain(node, ctx, target_width: str | None) -> str:
    terms, ops = _flatten_arith_chain(node)
    widths = [_width.infer_width(term, ctx) for term in terms]
    width = _effective_width(target_width, *widths)
    rendered = [_qualify_for_cast(term, render_expression(term, ctx, target_width=width)) for term in terms]

    pieces = [f"unsigned({rendered[0]})"]
    for op, term_text in zip(ops, rendered[1:]):
        pieces.append(f"{op} unsigned({term_text})")
    return f"slv({' '.join(pieces)})"


def _render_shift(node, ctx, target_width: str | None) -> str:
    """`<<`/`>>` (`vast.Sll`/`vast.Srl`): `ieee.numeric_std.shift_left`/
    `shift_right` on the left operand, by an amount converted to a plain
    `natural` via `to_integer(unsigned(...))`. The left operand is rendered
    at the shift's own self-determined width -- `width.infer_width`
    already defines that as the left operand's own width, never widened by
    the shift amount -- and the right operand (the shift amount) is
    rendered at its own self-determined width (`target_width=None`), per
    the same self-determined/context-determined split every other operand
    in this module follows.
    """
    op_name = _SHIFT_OPS[type(node)]
    self_width = _width.infer_width(node, ctx)
    left = _qualify_for_cast(node.left, render_expression(node.left, ctx, target_width=self_width.text))
    amount = _qualify_for_cast(node.right, render_expression(node.right, ctx, target_width=None))
    core = f"slv({op_name}(unsigned({left}), to_integer(unsigned({amount}))))"
    return _fit(core, self_width, target_width, node, ctx)


def _render_boolean_condition(node, ctx) -> str:
    """Render `node` as a genuine VHDL `boolean` -- `ite`'s `i` parameter
    is strictly `boolean`, with no implicit conversion from `sl`.

    `Land`/`Lor`/`Ulnot` recurse into their own operands through this same
    function rather than delegating the whole subtree to
    `render_expression`: that general renderer's `_render_logical_binary`/
    `_render_logical_not` produce an `sl` result (VHDL's `and`/`or`/`not`
    overload for `std_ulogic`, the type every other value-context operand
    in this module is), not `boolean`, and `mkQP.v`'s multi-term `?:`
    conditions are the first case in the corpus deep enough to reach a
    `Land`/`Lor`/`Ulnot` as this function's own top-level argument rather
    than only as an interior operand of some other value expression.
    """
    if isinstance(node, tuple(_EQUALITY_OPS) + tuple(_RELATIONAL_OPS)):
        return render_expression(node, ctx, target_width=None)
    if isinstance(node, vast.Land):
        return f"({_render_boolean_condition(node.left, ctx)} and {_render_boolean_condition(node.right, ctx)})"
    if isinstance(node, vast.Lor):
        return f"({_render_boolean_condition(node.left, ctx)} or {_render_boolean_condition(node.right, ctx)})"
    if isinstance(node, vast.Ulnot):
        return f"(not {_render_boolean_condition(node.right, ctx)})"
    if isinstance(node, vast.Identifier) and ctx.is_param(node.name):
        return f"({ctx.generic_name[node.name]} /= 0)"
    text = render_expression(node, ctx, target_width=None)
    return f"({text} = '1')"


def _render_cond(node: vast.Cond, ctx, target_width: str | None) -> str:
    true_width = _width.infer_width(node.true_value, ctx)
    false_width = _width.infer_width(node.false_value, ctx)
    width = _effective_width(target_width, true_width, false_width)
    true_text = _qualify_for_cast(node.true_value, render_expression(node.true_value, ctx, target_width=width))
    false_text = _qualify_for_cast(node.false_value, render_expression(node.false_value, ctx, target_width=width))
    cond_text = _render_boolean_condition(node.cond, ctx)
    return f"ite({cond_text}, {true_text}, {false_text})"


_BOOLEAN_RESULT_TYPES = tuple(_EQUALITY_OPS) + tuple(_RELATIONAL_OPS) + (vast.Land, vast.Lor, vast.Ulnot)


def _render_concat(node: vast.Concat, ctx, target_width: str | None) -> str:
    self_width = _width.infer_width(node, ctx)
    pieces = []
    for item in node.list:
        # A comparison or logical operand (`mkQP.v` concatenates one
        # directly, unwrapped by any surrounding `Land`/`Lor`, into a
        # multi-bit selector) is context-determined to a plain VHDL
        # `boolean` at `target_width=None`, the shape
        # `_render_boolean_condition` wants; `&` needs an `sl` value on
        # every operand instead, so this passes `target_width="1"` for
        # exactly the boolean-result node types, the same width
        # `_render_logical_binary` already hands its own two operands, and
        # lets `_render_equality`/`_render_relational`/etc.'s own
        # `toSl(...)` wrap do the conversion.
        item_target = "1" if isinstance(item, _BOOLEAN_RESULT_TYPES) else None
        pieces.append(render_expression(item, ctx, target_width=item_target))
    core = pieces[0] if len(pieces) == 1 else "(" + " & ".join(pieces) + ")"
    return _fit(core, self_width, target_width, node, ctx)


def _render_repeat(node: vast.Repeat, ctx, target_width: str | None) -> str:
    operand = _width.repeated_operand(node)
    operand_width = _width.infer_width(operand, ctx)
    if operand_width.value != 1:
        raise UnsupportedConstruct(
            "replication of a multi-bit operand outside the initializer path", ctx.path, getattr(node, "lineno", 0)
        )
    operand_text = render_expression(operand, ctx, target_width="1")
    count_text = _width._node_to_text(node.times, ctx)
    count_vhdl = count_text if count_text.isdigit() else _width.symbolic(count_text)
    core = f"slvAll({count_vhdl}, {operand_text})"
    self_width = _width.infer_width(node, ctx)
    return _fit(core, self_width, target_width, node, ctx)


def _base_text(var_node, ctx) -> str:
    if isinstance(var_node, vast.Identifier):
        return ctx.name_for(var_node.name)
    return render_expression(var_node, ctx, target_width=None)


def _render_partselect(node: vast.Partselect, ctx, target_width: str | None) -> str:
    base = _base_text(node.var, ctx)
    msb_text = _width.symbolic(_width._node_to_text(node.msb, ctx))
    lsb_text = _width.symbolic(_width._node_to_text(node.lsb, ctx))
    core = f"{base}({msb_text} downto {lsb_text})"
    self_width = _width.infer_width(node, ctx)
    return _fit(core, self_width, target_width, node, ctx)


def _render_pointer(node: vast.Pointer, ctx, target_width: str | None) -> str:
    base = _base_text(node.var, ctx)
    base_name = node.var.name if isinstance(node.var, vast.Identifier) else None
    is_memory = getattr(ctx, "is_memory", None)
    if base_name is not None and is_memory is not None and is_memory(base_name):
        # A memory-array element access: the index selects a whole element,
        # not a bit, and VHDL array indexing requires an integer, never an
        # `slv` directly, so the index is converted through
        # `to_integer(unsigned(...))`. `RAM[ADDRA]`/`arr[head]` are the only
        # shapes this branch exists for; a plain vector's bit-select (the
        # `is_memory` is False path below) never occurs with a non-constant
        # index anywhere in the corpus, so that path is left exactly as it
        # was before memory support existed.
        index_text = _qualify_for_cast(node.ptr, render_expression(node.ptr, ctx, target_width=None))
        core = f"{base}(to_integer(unsigned({index_text})))"
        self_width = _width.infer_width(node, ctx)
        return _fit(core, self_width, target_width, node, ctx)
    index_text = _bit_select_index_text(node.ptr, ctx)
    core = f"{base}({index_text})"
    self_width = _width.WidthExpr(1, "1")
    return _fit(core, self_width, target_width, node, ctx)


def _bit_select_index_text(ptr_node, ctx) -> str:
    """Render a plain (non-memory) bit-select's index as VHDL text.

    VHDL requires an `integer` here, never an `slv`/`sl` literal:
    `signal(1)` is legal, `signal("000...01")` is not. `render_expression`
    on a bare `IntConst` renders it as a vector or scalar literal sized by
    context, exactly wrong for an index position -- the shape
    `mkAxisTransportLayer.v`'s own `D_OUT[1]`/`D_OUT[0]` bit-selects reach
    (the thirteen-file corpus has no plain-vector bit-select with a
    constant index at all, so this path was unexercised before it). A
    constant index renders as a bare decimal integer; a non-constant index
    falls back to the same `to_integer(unsigned(...))` conversion the
    memory-element path above already uses, so a future non-constant
    plain-vector bit-select does not repeat this same defect.
    """
    if isinstance(ptr_node, vast.IntConst):
        return str(_width.parse_int_literal(ptr_node.value))
    index_text = render_expression(ptr_node, ctx, target_width=None)
    return f"to_integer(unsigned({index_text}))"
