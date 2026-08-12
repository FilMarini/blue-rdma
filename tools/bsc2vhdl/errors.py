"""The single exception type the transpiler raises on unsupported input.

`UnsupportedConstruct` is the only exception the CLI catches and turns into
a nonzero exit. On any Verilog construct outside the supported BSC subset,
a pass raises this naming the construct and its `file:line`, and the CLI
writes nothing for that input file. No partial output, no stubs.

The contract: a refusal names the construct first, then the location, and
the caller writes nothing. `refusal_message` is the one place that message
text is built, so every raise site and every test that matches against it
stay in sync by construction.
"""
from __future__ import annotations

from pathlib import Path


def refusal_message(construct: str, path: Path, lineno: int) -> str:
    """Return the stable refusal text for `construct` at `path:lineno`."""
    return f"{construct} at {path}:{lineno} is outside the supported BSC subset"


class UnsupportedConstruct(Exception):
    """Raised for any Verilog construct outside the supported BSC subset."""

    def __init__(self, construct: str, path: Path, lineno: int) -> None:
        self.construct = construct
        self.path = path
        self.lineno = lineno
        super().__init__(str(self))

    def __str__(self) -> str:
        return refusal_message(self.construct, self.path, self.lineno)
