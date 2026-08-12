"""Cross-module reference emission: VHDL `component` declarations only.

Owned in full by a later plan. Every blue-lib file, including this plan's
`RegN.v` tracer, instantiates nothing, so both functions return an empty
list unconditionally today. The eventual rule, locked here so the later
plan does not have to relitigate it: a VHDL `component` declaration plus a
plain (non-`entity`-prefixed) instantiation for every cross-module
reference, never `entity work.X` or `entity surf.X`, because GHDL analyzes
a `component`-declared but never analyzed unit with exit 0 while a direct
entity reference to a nonexistent unit fails with exit 1.
"""
from __future__ import annotations


def component_declarations(module_ir, ctx) -> list[str]:
    return []


def instantiations(module_ir, ctx) -> list[str]:
    return []
