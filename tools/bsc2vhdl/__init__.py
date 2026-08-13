"""bsc2vhdl: a purpose-built transpiler from BSC-generated Verilog to VHDL.

Translates the narrow subset of Verilog that the Bluespec Compiler (BSC)
2023.01 emits into surf-idiomatic, GHDL-clean VHDL. Takes explicit input
files and an explicit output directory; has no runtime dependency on any
other repository, on any lint tool, or on a default destination.
"""
from __future__ import annotations

from .emit import emit_vhdl
from .errors import UnsupportedConstruct
from .parser import parse_module

__version__ = "0.1.0"

__all__ = ["emit_vhdl", "parse_module", "UnsupportedConstruct", "__version__"]
