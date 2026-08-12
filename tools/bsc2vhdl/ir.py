"""The intermediate representation the emitter reads.

Every width bound is stored as the original Verilog text so `width.py`
owns all evaluation; nothing here folds a parameter-dependent bound into a
number.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ParamDecl:
    name: str
    default_expr: str
    default_value: int


@dataclass(frozen=True)
class PortDecl:
    name: str
    direction: str
    msb_expr: str | None
    lsb_expr: str | None
    is_scalar: bool


@dataclass(frozen=True)
class SignalDecl:
    name: str
    msb_expr: str | None
    lsb_expr: str | None
    is_scalar: bool
    is_memory: bool
    # Populated only when `is_memory` is True: the two Verilog-text bounds of
    # the memory's own declared range (`reg [W-1:0] arr[LOW:HIGH]`), in the
    # same plain-Verilog-name text form `msb_expr`/`lsb_expr` already use.
    # `emit.py` resolves these to VHDL text itself (generics and
    # localparam-derived constants alike), the same way it already resolves
    # `msb_expr`/`lsb_expr`.
    depth_low_expr: str | None = None
    depth_high_expr: str | None = None


@dataclass(frozen=True)
class InstanceParam:
    """One parameter override at an instantiation site (`.width(32'd170)`).

    `value` is the override's own resolved integer, read once by
    `parser.py` the same way a `Parameter` declaration's own default is
    resolved; nothing downstream re-parses `value_expr`."""

    name: str
    value_expr: str
    value: int


@dataclass(frozen=True)
class InstancePort:
    """One port association at an instantiation site. `actual_expr` is the
    connected signal's plain Verilog name, or `None` for the Verilog
    `.portname()` open-port idiom (`mkAxisTransportLayer.v`'s two
    unconnected `mkTransportLayer` outputs)."""

    name: str
    actual_expr: str | None


@dataclass(frozen=True)
class InstanceDecl:
    """One module instantiation. `module` is the referenced module's own
    name, never renamed; `name` is this instance's own label, used verbatim
    as the VHDL instantiation label since it already carries embedded
    uppercase letters (BSC's own naming) and needs no mangling."""

    module: str
    name: str
    params: tuple[InstanceParam, ...]
    ports: tuple[InstancePort, ...]


@dataclass(frozen=True)
class LocalparamDecl:
    """A Verilog `localparam`: a derived elaboration-time value, never
    exposed as a generic. `value_expr` is already-final VHDL text (bare
    integers, generic names, and `ite(...)` for a ternary default), computed
    once by `parser.py` at parse time, since a localparam's value never
    depends on anything the emitter decides."""

    name: str
    value_expr: str


@dataclass(frozen=True)
class ModuleIR:
    name: str
    source_path: Path
    params: tuple[ParamDecl, ...]
    ports: tuple[PortDecl, ...]
    signals: tuple[SignalDecl, ...]
    localparams: tuple[LocalparamDecl, ...] = ()
    assigns: tuple = ()
    always_blocks: tuple = ()
    initials: tuple = ()
    instances: tuple = ()
