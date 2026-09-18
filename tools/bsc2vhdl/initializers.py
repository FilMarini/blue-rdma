"""Translates an `initial`-block power-on value into a VHDL signal default.

Implements every idiom the corpus actually uses. Five classifications of
an initial-block right-hand side, recognized structurally from the
expression tree rather than by matching source text. First, a replication
of the two-bit literal `2'b10` whose count is a parameter expression: a
call to `bsvAltInit`, a pure function emitted into the architecture
declarative region only when at least one declaration actually calls it.
Second, a replication of the single bit `1'b0` (or a literal zero of any
base): `(others => '0')`. Third, a plain reference to another declared
signal or port -- the idiom `SizedFIFO.v` line 100 uses to seed every ring
element from `D_OUT` -- resolved through the name map. Fourth, a bare
single-bit literal (`1'b1`, `1'b0`) on a scalar declaration -- the idiom
every corpus status flag (`full_reg`, `empty_reg`, `ring_empty`,
`not_ring_full`, `hasodata`, ...) uses, since a one-bit register has no
replication syntax to write in the first place. Fifth, a plain sized
literal in any base directly initializing a vector register with no
replication at all -- `mkQP.v`'s and `mkTransportLayer.v`'s giant
`initial` block idiom (`cntrl_dqpnReg = 24'hAAAAAA;`), rendered as a
quoted VHDL bit-string literal at the literal's own declared width.
Anything else raises `UnsupportedConstruct` naming the file and line.

The `bsvAltInit` formula comes from Verilog concatenation-then-truncation
semantics: the repeated two-bit group is `2'b10`, so after truncation to
the low `W` bits, bit `i` is `'1'` exactly when `i` is odd, independent of
whether `W` is even or odd.

Array and memory initializers reuse the same three classifications for
the *element* default and wrap the result in a single `others` aggregate:
`initial_for` walks the initial block's own `for` loop, confirms the
assigned expression makes no reference to the loop variable (an
index-dependent element value would need a real per-element initializer,
which nothing in the corpus needs and which an `others` aggregate cannot
express), and raises if it does rather than silently emitting a wrong
value for every element but one.
"""
from __future__ import annotations

import pyverilog.vparser.ast as vast

from .errors import UnsupportedConstruct
from . import width as _width

_BSV_ALT_INIT_NAME = "bsvAltInit"

_BSV_ALT_INIT_LINES = (
    f"function {_BSV_ALT_INIT_NAME} (size : positive) return slv is",
    "   variable ret : slv(size-1 downto 0);",
    "begin",
    "   for i in 0 to size-1 loop",
    "      if (i mod 2) = 1 then",
    "         ret(i) := '1';",
    "      else",
    "         ret(i) := '0';",
    "      end if;",
    "   end loop;",
    "   return ret;",
    f"end function {_BSV_ALT_INIT_NAME};",
)


def initializer_for(decl, initials, ctx) -> str | None:
    """Return the VHDL default-value text for scalar/vector `decl`, or `None`."""
    for initial in initials:
        assignment = _find_assignment(initial, decl.name)
        if assignment is not None:
            return _classify_initializer_rhs(assignment.right.var, decl, ctx)
    return None


def memory_initializer_for(decl, initials, ctx) -> str | None:
    """Return the `others =>`-wrapped VHDL default text for a memory-array
    signal, or `None` when the original never initializes it."""
    for initial in initials:
        found = _find_memory_element_assignment(initial, decl.name, ctx)
        if found is None:
            continue
        loop_var, rhs = found
        _assert_no_loop_var_reference(rhs, loop_var, ctx)
        return _classify_initializer_rhs(rhs, decl, ctx)
    return None


def helper_functions(used: set[str]) -> list[str]:
    """Return the architecture-declarative-region function bodies needed."""
    if _BSV_ALT_INIT_NAME not in used:
        return []
    return [f"   {line}" for line in _BSV_ALT_INIT_LINES]


def _find_assignment(initial_node, target_name: str):
    block = initial_node.statement
    statements = block.statements if isinstance(block, vast.Block) else (block,)
    for statement in statements:
        if not isinstance(statement, vast.BlockingSubstitution):
            continue
        if getattr(statement.left.var, "name", None) == target_name:
            return statement
    return None


def _find_memory_element_assignment(initial_node, target_name: str, ctx):
    block = initial_node.statement
    statements = block.statements if isinstance(block, vast.Block) else (block,)
    for statement in statements:
        if not isinstance(statement, vast.ForStatement):
            continue
        loop_var = _for_loop_variable(statement, ctx)
        body = statement.statement
        body_statements = body.statements if isinstance(body, vast.Block) else (body,)
        for inner in body_statements:
            if not isinstance(inner, vast.BlockingSubstitution):
                continue
            target = inner.left.var
            if (
                isinstance(target, vast.Pointer)
                and isinstance(target.var, vast.Identifier)
                and target.var.name == target_name
            ):
                return loop_var, inner.right.var
    return None


def _for_loop_variable(for_node: vast.ForStatement, ctx) -> str:
    pre = for_node.pre
    if isinstance(pre, vast.BlockingSubstitution) and isinstance(pre.left.var, vast.Identifier):
        return pre.left.var.name
    raise UnsupportedConstruct("for-loop initializer shape", ctx.path, getattr(for_node, "lineno", 0))


def _assert_no_loop_var_reference(node, loop_var: str, ctx) -> None:
    if isinstance(node, vast.Identifier) and node.name == loop_var:
        raise UnsupportedConstruct(
            "index-dependent array initializer", ctx.path, getattr(node, "lineno", 0)
        )
    for child in node.children():
        _assert_no_loop_var_reference(child, loop_var, ctx)


def _classify_initializer_rhs(rhs, decl, ctx) -> str:
    if isinstance(rhs, vast.Repeat):
        concat = rhs.value
        if isinstance(concat, vast.Concat) and len(concat.list) == 1 and isinstance(concat.list[0], vast.IntConst):
            bits = _literal_bits(concat.list[0].value, ctx, rhs)
            if all(bit == "0" for bit in bits):
                return "(others => '0')"
            if bits == "10":
                size_expr = _width.symbolic_size(decl.msb_expr, decl.lsb_expr)
                return f"{_BSV_ALT_INIT_NAME}({size_expr})"
    if isinstance(rhs, vast.Identifier):
        return ctx.name_for(rhs.name)
    if isinstance(rhs, vast.IntConst):
        bits = _literal_bits(rhs.value, ctx, rhs)
        if decl.is_scalar:
            if len(bits) == 1:
                return f"'{bits}'"
        else:
            # A plain (non-replicated) sized literal directly initializing a
            # vector register -- `mkQP.v`'s and `mkTransportLayer.v`'s giant
            # `initial` block uses this for every one of its scratch-value
            # assignments (`cntrl_dqpnReg = 24'hAAAAAA;`,
            # `sq_retryHandler_retryCntReg = 3'h2;`, ...), none of which is a
            # replication of a one- or two-bit pattern. `_literal_bits`
            # already renders the literal's own declared width as a bit
            # string regardless of base, the same conversion
            # `expr.py::_render_int_const` performs for a vector-context
            # literal everywhere else in the emitter.
            return f'"{bits}"'
    raise UnsupportedConstruct("initial-block pattern", ctx.path, getattr(rhs, "lineno", 0))


def _literal_bits(text: str, ctx, node) -> str:
    """Render a sized Verilog literal's own declared width as a plain bit
    string, in any of the four bases BSC's own output uses. The binary path
    keeps returning its digits verbatim (byte-identical to before this
    function accepted other bases); the other three bases go through
    `width.parse_int_literal` for the value and format it to the literal's
    own size, matching `expr.py::_render_int_const`'s identical conversion.
    """
    if "'" not in text:
        raise UnsupportedConstruct("decimal literal in initial block", ctx.path, getattr(node, "lineno", 0))
    prefix, rest = text.split("'", 1)
    base = rest[0].lower()
    if base == "b":
        return rest[1:]
    if base not in ("h", "o", "d"):
        raise UnsupportedConstruct("non-binary literal in initial block", ctx.path, getattr(node, "lineno", 0))
    if not prefix:
        raise UnsupportedConstruct("unsized literal in initial block", ctx.path, getattr(node, "lineno", 0))
    width = int(prefix)
    value = _width.parse_int_literal(text)
    return format(value, f"0{width}b")
