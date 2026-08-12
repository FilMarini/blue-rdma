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
    depth_expr: str | None


@dataclass(frozen=True)
class ModuleIR:
    name: str
    source_path: Path
    params: tuple[ParamDecl, ...]
    ports: tuple[PortDecl, ...]
    signals: tuple[SignalDecl, ...]
    assigns: tuple = ()
    always_blocks: tuple = ()
    initials: tuple = ()
    instances: tuple = ()
