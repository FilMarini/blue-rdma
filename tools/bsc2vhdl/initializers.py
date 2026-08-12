"""Translates an `initial`-block power-on value into a VHDL signal default.

Implements the two idioms `RegN.v` needs: the all-zero replication
(`(others => '0')`) and the alternating power-on pattern
`{((width + 1)/2){2'b10}}`, which becomes a call to `bsvAltInit`, a pure
function emitted into the architecture declarative region only when at
least one declaration actually uses it.

The `bsvAltInit` formula comes from Verilog concatenation-then-truncation
semantics: the repeated two-bit group is `2'b10`, so after truncation to
the low `W` bits, bit `i` is `'1'` exactly when `i` is odd, independent of
whether `W` is even or odd. A later plan owns array and memory
initializers and the rest of the corpus's idioms.
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
    """Return the VHDL default-value text for `decl`, or `None`."""
    for initial in initials:
        assignment = _find_assignment(initial, decl.name)
        if assignment is not None:
            return _initializer_expr(assignment.right.var, decl, ctx)
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
        if isinstance(statement, vast.BlockingSubstitution) and statement.left.var.name == target_name:
            return statement
    return None


def _initializer_expr(rhs, decl, ctx) -> str:
    if isinstance(rhs, vast.Repeat):
        concat = rhs.value
        if isinstance(concat, vast.Concat) and len(concat.list) == 1 and isinstance(concat.list[0], vast.IntConst):
            bits = _literal_bits(concat.list[0].value, ctx, rhs)
            if all(bit == "0" for bit in bits):
                return "(others => '0')"
            if bits == "10":
                size_expr = _width.symbolic_size(decl.msb_expr, decl.lsb_expr)
                return f"{_BSV_ALT_INIT_NAME}({size_expr})"
    raise UnsupportedConstruct("initial-block pattern", ctx.path, getattr(rhs, "lineno", 0))


def _literal_bits(text: str, ctx, node) -> str:
    if "'" not in text:
        raise UnsupportedConstruct("decimal literal in initial block", ctx.path, getattr(node, "lineno", 0))
    _, rest = text.split("'", 1)
    base = rest[0].lower()
    if base != "b":
        raise UnsupportedConstruct("non-binary literal in initial block", ctx.path, getattr(node, "lineno", 0))
    return rest[1:]
