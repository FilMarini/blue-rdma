"""The single exception type the transpiler raises on unsupported input.

`UnsupportedConstruct` is the only exception the CLI catches and turns into
a nonzero exit. On any Verilog construct outside the supported BSC subset,
a pass raises this naming the construct and its `file:line`, and the CLI
writes nothing for that input file. No partial output, no stubs.
"""
from __future__ import annotations

from pathlib import Path


class UnsupportedConstruct(Exception):
    """Raised for any Verilog construct outside the supported BSC subset."""

    def __init__(self, construct: str, path: Path, lineno: int) -> None:
        self.construct = construct
        self.path = path
        self.lineno = lineno
        super().__init__(str(self))

    def __str__(self) -> str:
        return f"{self.construct} at {self.path}:{self.lineno} is outside the supported BSC subset"
