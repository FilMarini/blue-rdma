"""The complete VHDL-93 plus VHDL-2008 reserved-word list.

Getting this list wrong either mangles names that don't need it or, worse,
misses one, which fails only at GHDL analyze time on whatever corpus file
happens to use that exact word. Case-insensitive: VHDL identifiers are.
"""
from __future__ import annotations

VHDL_RESERVED_WORDS: frozenset[str] = frozenset(
    {
        "abs", "access", "after", "alias", "all", "and", "architecture", "array",
        "assert", "assume", "assume_guarantee", "attribute", "begin", "block",
        "body", "buffer", "bus", "case", "component", "configuration", "constant",
        "context", "cover", "default", "disconnect", "downto", "else", "elsif",
        "end", "entity", "exit", "fairness", "file", "for", "force", "function",
        "generate", "generic", "group", "guarded", "if", "impure", "in",
        "inertial", "inout", "is", "label", "library", "linkage", "literal",
        "loop", "map", "mod", "nand", "new", "next", "nor", "not", "null", "of",
        "on", "open", "or", "others", "out", "package", "parameter", "port",
        "postponed", "procedure", "process", "property", "protected", "pure",
        "range", "record", "register", "reject", "release", "rem", "report",
        "restrict", "restrict_guarantee", "return", "rol", "ror", "select",
        "sequence", "severity", "shared", "signal", "sla", "sll", "sra", "srl",
        "strong", "subtype", "then", "to", "transport", "type", "unaffected",
        "units", "until", "use", "variable", "view", "vmode", "vpkg", "vprop",
        "vunit", "wait", "when", "while", "with", "xnor", "xor",
    }
)
