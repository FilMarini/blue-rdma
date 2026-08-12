"""Builds the whole VHDL file text for one module and owns its layout.

Fixed structure, in order: the SLAC license comment block, a generated-file
banner naming the source `.v` file and the transpiler version with no
wall-clock timestamp anywhere (so a re-run at a fixed tool version is
byte-identical by construction), the fixed library preamble emitted
identically in every file, the entity (generic and port clauses aligned by
construction, never by shelling out to `vsg`), the architecture with its
mandatory blank lines, and `end rtl;`.

Generic typing rule, locked here because it decides whether the
equivalence harness can drive the entity at all: a Verilog `parameter`
becomes an integer-typed VHDL generic named by uppercasing the parameter
name and appending `_G`. A parameter used as a width bound becomes
`positive`; a parameter used as a value becomes `natural`, converted at
its use site with `toSlv(<GENERIC>, <width>)` wherever a vector context
needs it. Never emits a `TPD_G` generic or any delay clause on any
assignment: these entities are compared cycle by cycle against their
Verilog originals, and any output delay breaks bit-exactness by
construction. A parameter named `guarded` (case-insensitively) is never
emitted as a generic at all: the corpus's own `guarded` parameter is read
only inside the `$display`-guarded error-reporting block this emitter
already drops, so a `GUARDED_G` generic would be entirely unreferenced
dead surface, and the hand-written Phase 2 blue-lib entities already
established the precedent of dropping it rather than carrying it through.
A module with no remaining generics after that drop gets no `generic`
clause at all, since VHDL has no syntax for an empty one.
"""
from __future__ import annotations

import ast as _ast
import re
from dataclasses import dataclass, field
from pathlib import Path

import pyverilog.vparser.ast as vast

from . import expr as _expr
from . import initializers as _initializers
from . import instantiate as _instantiate
from . import strip as _strip
from . import stmt as _stmt
from . import width as _width
from .errors import UnsupportedConstruct
from .mangle import NameMap

__all__ = ["emit_vhdl"]

INDENT = "   "

_DROPPED_GENERIC_NAMES = frozenset({"guarded"})

_SLAC_HEADER = (
    "-------------------------------------------------------------------------------\n"
    "-- This file is part of 'SLAC Firmware Standard Library'.\n"
    "-- It is subject to the license terms in the LICENSE.txt file found in the\n"
    "-- top-level directory of this distribution and at:\n"
    "--    https://confluence.slac.stanford.edu/display/ppareg/LICENSE.html.\n"
    "-- No part of 'SLAC Firmware Standard Library', including this file,\n"
    "-- may be copied, modified, propagated, or distributed except according to\n"
    "-- the terms contained in the LICENSE.txt file.\n"
    "-------------------------------------------------------------------------------"
)

_LIBRARY_PREAMBLE = (
    "library ieee;\n"
    "use ieee.std_logic_1164.all;\n"
    "use ieee.numeric_std.all;\n"
    "\n"
    "library surf;\n"
    "use surf.StdRtlPkg.all;"
)


@dataclass
class _EmitContext:
    path: Path
    name_map: NameMap
    generic_name: dict
    param_kind: dict
    param_names: set
    localparam_name: dict = field(default_factory=dict)
    memory_names: set = field(default_factory=set)
    shared_memory_names: set = field(default_factory=set)
    signal_size: dict = field(default_factory=dict)

    def is_param(self, name: str) -> bool:
        return name in self.param_names

    def is_memory(self, name: str) -> bool:
        return name in self.memory_names

    def is_shared_memory(self, name: str) -> bool:
        return name in self.shared_memory_names

    def name_for(self, name: str) -> str:
        localparam = self.localparam_name.get(name.lower())
        if localparam is not None:
            return localparam
        try:
            return self.name_map.signal(name)
        except KeyError:
            return self.name_map.port(name)

    def target_width_for(self, name: str) -> str | None:
        return self.signal_size.get(name)


def _memories_with_multiple_writers(module_ir) -> set:
    """Memory names written from more than one surviving `always` block.

    A VHDL signal has one driver per process: two independent clocked
    processes each writing an element of the same memory array (BRAM2.v's
    two independent write ports, one per clock domain) is a genuine
    multiple-driver conflict on a signal. `std_logic`/`std_logic_vector`
    resolution silently turns that into 'X' on every element one process
    has written and the other has not, rather than raising an elaboration
    error -- caught by replaying Phase 2's own committed goldens against
    the transpiled fixture, not by inspection of the emitted text. A
    `shared variable`, the same modeling choice the hand-written
    BRAM2.vhd makes for the identical reason (see its own header), has no
    such conflict: an assignment to it takes effect immediately, with no
    driver to resolve. A memory written from at most one process
    (SizedFIFO.v's `arr`) stays a plain signal, since a signal with a
    single driver has nothing to resolve either.
    """
    memory_names = {signal.name for signal in module_ir.signals if signal.is_memory}
    if not memory_names:
        return set()
    kept_always_blocks, _dropped = _strip.partition_always_blocks(module_ir)
    writer_counts: dict = {name: 0 for name in memory_names}
    for always_block in kept_always_blocks:
        targets = _strip._assignment_targets(always_block.statement)
        for name in targets & memory_names:
            writer_counts[name] += 1
    return {name for name, count in writer_counts.items() if count > 1}


def emit_vhdl(module_ir, tool_version: str = "0.1.0") -> str:
    name_map = NameMap.build(module_ir)
    generic_name = {
        param.name: f"{param.name.upper()}_G"
        for param in module_ir.params
        if param.name.lower() not in _DROPPED_GENERIC_NAMES
    }
    param_kind = {param.name: _param_kind(param.name, module_ir) for param in module_ir.params}
    localparam_name = {localparam.name.lower(): f"{localparam.name.upper()}_C" for localparam in module_ir.localparams}
    memory_names = {signal.name for signal in module_ir.signals if signal.is_memory}
    shared_memory_names = _memories_with_multiple_writers(module_ir)

    ctx = _EmitContext(
        path=module_ir.source_path,
        name_map=name_map,
        generic_name=generic_name,
        param_kind=param_kind,
        param_names={param.name for param in module_ir.params},
        localparam_name=localparam_name,
        memory_names=memory_names,
        shared_memory_names=shared_memory_names,
    )
    # Every port and signal gets an entry, scalar ones included: a scalar
    # assignment target's own width is "1", the same convention
    # `_identifier_width` already falls back to when a name carries no
    # entry at all, but an *assigned* target needs that "1" to actually
    # reach `render_expression` as an explicit `target_width` so a
    # comparison or logical result renders through the `toSl(...)` wrap
    # instead of as a bare boolean assigned straight to a `sl` signal
    # (`SizedFIFO.v`'s `ring_empty <= (next_head == tail);` is the corpus
    # case this closes).
    for port in module_ir.ports:
        ctx.signal_size[port.name] = "1" if port.is_scalar else _width.symbolic_size(port.msb_expr, port.lsb_expr)
    for signal in module_ir.signals:
        ctx.signal_size[signal.name] = (
            "1" if signal.is_scalar else _width.symbolic_size(signal.msb_expr, signal.lsb_expr)
        )

    entity_lines = _render_entity(module_ir, param_kind, generic_name)
    declarative_lines, used_helpers = _render_declarations(module_ir, ctx)
    body_lines = _render_body(module_ir, ctx, used_helpers)

    lines: list[str] = []
    lines.append(_SLAC_HEADER)
    lines.append(_generated_banner(module_ir.source_path, tool_version))
    lines.append("")
    lines.append(_LIBRARY_PREAMBLE)
    lines.append("")
    lines.extend(entity_lines)
    lines.append("")
    lines.append(f"architecture rtl of {module_ir.name} is")
    lines.append("")
    lines.extend(declarative_lines)
    lines.append("")
    lines.append("begin")
    lines.append("")
    lines.extend(body_lines)
    lines.append("")
    lines.append("end rtl;")

    text = "\n".join(line.rstrip() for line in lines)
    return text + "\n"


def _generated_banner(source_path: Path, tool_version: str) -> str:
    return (
        "-------------------------------------------------------------------------------\n"
        f"-- Generated by bsc2vhdl {tool_version} from {source_path.name}.\n"
        "-- Do not hand-edit: re-run the transpiler to regenerate this file.\n"
        "-------------------------------------------------------------------------------"
    )


def _param_kind(param_name: str, module_ir) -> str:
    width_texts: list[str] = []
    for port in module_ir.ports:
        if port.msb_expr:
            width_texts.append(port.msb_expr)
        if port.lsb_expr:
            width_texts.append(port.lsb_expr)
    for signal in module_ir.signals:
        if signal.msb_expr:
            width_texts.append(signal.msb_expr)
        if signal.lsb_expr:
            width_texts.append(signal.lsb_expr)
        if signal.depth_low_expr:
            width_texts.append(signal.depth_low_expr)
        if signal.depth_high_expr:
            width_texts.append(signal.depth_high_expr)
    pattern = re.compile(rf"\b{re.escape(param_name)}\b")
    return "positive" if any(pattern.search(text) for text in width_texts) else "natural"


def _vector_type(msb_expr, lsb_expr, is_scalar) -> str:
    if is_scalar or msb_expr is None:
        return "sl"
    return f"slv({_width.symbolic(msb_expr)} downto {_width.symbolic(lsb_expr)})"


def _render_entity(module_ir, param_kind, generic_name) -> list[str]:
    lines = [f"entity {module_ir.name} is"]
    lines.extend(_render_generic_clause(module_ir, param_kind, generic_name))
    lines.extend(_render_port_clause(module_ir))
    lines.append(f"end {module_ir.name};")
    return lines


def _render_generic_clause(module_ir, param_kind, generic_name) -> list[str]:
    entries = [
        (generic_name[param.name], param_kind[param.name], str(param.default_value))
        for param in module_ir.params
        if param.name in generic_name
    ]
    if not entries:
        return []
    max_name = max(len(name) for name, _, _ in entries)
    max_type = max(len(kind) for _, kind, _ in entries)
    lines = [f"{INDENT}generic ("]
    for index, (name, kind, default) in enumerate(entries):
        terminator = ");" if index == len(entries) - 1 else ";"
        lines.append(
            f"{INDENT * 2}{name.ljust(max_name + 1)}: {kind.ljust(max_type + 1)}:= {default}{terminator}"
        )
    return lines


def _render_port_clause(module_ir) -> list[str]:
    ins = [port for port in module_ir.ports if port.direction == "in"]
    outs = [port for port in module_ir.ports if port.direction == "out"]
    entries = [
        (port.name, port.direction, _vector_type(port.msb_expr, port.lsb_expr, port.is_scalar))
        for port in ins + outs
    ]
    max_name = max(len(name) for name, _, _ in entries)
    max_dir = max(len(direction) for _, direction, _ in entries)
    lines = [f"{INDENT}port ("]
    for index, (name, direction, type_text) in enumerate(entries):
        terminator = ");" if index == len(entries) - 1 else ";"
        lines.append(
            f"{INDENT * 2}{name.ljust(max_name + 1)}: {direction.ljust(max_dir)} {type_text}{terminator}"
        )
    return lines


def _render_declarations(module_ir, ctx) -> tuple[list[str], set[str]]:
    used_helpers: set[str] = set()
    lines: list[str] = []

    if module_ir.localparams:
        for localparam in module_ir.localparams:
            const_name = ctx.localparam_name[localparam.name.lower()]
            lines.append(f"{INDENT}constant {const_name} : natural := {localparam.value_expr};")
        lines.append("")

    # Scalars first, then memories: the only cross-signal dependency this
    # corpus has is a memory element's default referencing an already
    # (scalar) signal (`SizedFIFO.v`'s `arr` seeding every element from
    # `D_OUT`), never the reverse. VHDL requires a signal to be declared
    # before its name is visible to a later declaration in the same
    # declarative region, so the dependency's direction fixes the order.
    scalar_signals = [signal for signal in module_ir.signals if not signal.is_memory]
    memory_signals = [signal for signal in module_ir.signals if signal.is_memory]

    declaration_lines: list[str] = []
    for signal in scalar_signals:
        declaration_lines.extend(_render_scalar_declaration(signal, module_ir, ctx, used_helpers))
    for signal in memory_signals:
        declaration_lines.extend(_render_memory_declaration(signal, module_ir, ctx, used_helpers))

    helper_lines = _initializers.helper_functions(used_helpers)
    if helper_lines:
        lines.extend(helper_lines)
        lines.append("")
    lines.extend(declaration_lines)

    # A VHDL `component` declaration is a declarative item: it must appear
    # in the architecture's own declarative part, before `begin`, never
    # among its concurrent statements (confirmed directly against GHDL --
    # `-a` on a `component ... end component;` placed after `begin` fails
    # with "unexpected token 'is' in a concurrent statement list"). No file
    # in the thirteen-file corpus this emitter previously closed against
    # instantiates anything at all, so this call was dead code -- always
    # returning `[]` -- until the first file that actually does.
    component_lines = _instantiate.component_declarations(module_ir, ctx)
    if component_lines:
        if lines:
            lines.append("")
        lines.extend(component_lines)
    return lines, used_helpers


def _render_scalar_declaration(signal, module_ir, ctx, used_helpers: set[str]) -> list[str]:
    vhdl_name = ctx.name_map.signal(signal.name)
    type_text = _vector_type(signal.msb_expr, signal.lsb_expr, signal.is_scalar)
    default = _initializers.initializer_for(signal, module_ir.initials, ctx)
    if default is not None and "bsvAltInit(" in default:
        used_helpers.add("bsvAltInit")
    suffix = f" := {default}" if default is not None else ""
    return [f"{INDENT}signal {vhdl_name} : {type_text}{suffix};"]


def _render_memory_declaration(signal, module_ir, ctx, used_helpers: set[str]) -> list[str]:
    vhdl_name = ctx.name_map.signal(signal.name)
    element_type = _vector_type(signal.msb_expr, signal.lsb_expr, signal.is_scalar)
    # VSG's type-naming rule (`type_004`) requires PascalCase, so the type
    # name capitalizes the signal's own first letter even though the
    # signal itself stays camelCase (`ram` -> `RamType`, `arr` -> `ArrType`).
    type_name = f"{vhdl_name[0].upper()}{vhdl_name[1:]}Type"
    low = _render_declared_bound(signal.depth_low_expr, ctx)
    high = _render_declared_bound(signal.depth_high_expr, ctx)
    default = _initializers.memory_initializer_for(signal, module_ir.initials, ctx)
    if default is not None and "bsvAltInit(" in default:
        used_helpers.add("bsvAltInit")
    lines = [f"{INDENT}type {type_name} is array ({low} to {high}) of {element_type};"]
    suffix = f" := (others => {default})" if default is not None else ""
    kind = "shared variable" if ctx.is_shared_memory(signal.name) else "signal"
    lines.append(f"{INDENT}{kind} {vhdl_name} : {type_name}{suffix};")
    return lines


def _render_declared_bound(text: str, ctx) -> str:
    """Render a memory array's own declared depth bound (`0`, `MEMSIZE-1`,
    `p2depth2`, ...) as VHDL text.

    A small, self-contained mirror of `width.py`'s whitelisted-`ast`
    grammar (integer constants, unary +/-, and the four arithmetic binary
    operators), scoped to this one need: unlike a signal's own vector
    width, a memory's depth bound can name a *localparam* as well as a
    generic, and `width.py`'s own symbolic renderer has no localparam
    concept to consult. Kept local here rather than teaching `width.py`
    about localparams, since memory declarations are this module's own
    concern.
    """
    tree = _ast.parse(text.strip(), mode="eval")
    return _render_declared_bound_node(tree.body, ctx)


def _render_declared_bound_node(node, ctx) -> str:
    if isinstance(node, _ast.Constant) and isinstance(node.value, int):
        return str(node.value)
    if isinstance(node, _ast.Name):
        generic = ctx.generic_name.get(node.id)
        if generic is not None:
            return generic
        localparam = ctx.localparam_name.get(node.id.lower())
        if localparam is not None:
            return localparam
        raise UnsupportedConstruct(f"unresolved identifier {node.id!r} in array bound", ctx.path, 0)
    if isinstance(node, _ast.UnaryOp) and isinstance(node.op, (_ast.UAdd, _ast.USub)):
        value = _render_declared_bound_node(node.operand, ctx)
        return value if isinstance(node.op, _ast.UAdd) else f"-{value}"
    if isinstance(node, _ast.BinOp) and isinstance(node.op, (_ast.Add, _ast.Sub, _ast.Mult, _ast.FloorDiv, _ast.Div)):
        left = _render_declared_bound_node(node.left, ctx)
        right = _render_declared_bound_node(node.right, ctx)
        op = {_ast.Add: "+", _ast.Sub: "-", _ast.Mult: "*", _ast.FloorDiv: "/", _ast.Div: "/"}[type(node.op)]
        return f"{left}{op}{right}"
    raise UnsupportedConstruct("array bound expression", ctx.path, 0)


def _render_body(module_ir, ctx, used_helpers) -> list[str]:
    groups: list[list[str]] = []

    # The plain (non-`entity`-prefixed) instantiation statements themselves
    # are concurrent statements and belong here, after `begin`; their
    # matching `component` declarations belong in the declarative part
    # instead (see `_render_declarations`), never here.
    instantiation_lines = _instantiate.instantiations(module_ir, ctx)
    if instantiation_lines:
        groups.append(instantiation_lines)

    assign_lines = [_render_assign(assign, ctx) for assign in module_ir.assigns]
    if assign_lines:
        groups.append(assign_lines)

    kept_always_blocks, _dropped = _strip.partition_always_blocks(module_ir)
    process_lines: list[str] = []
    for index, always_block in enumerate(kept_always_blocks):
        if index > 0:
            process_lines.append("")
        process_lines.extend(_render_process(always_block, ctx))
    if process_lines:
        groups.append(process_lines)

    signal_by_original = {signal.name: signal for signal in module_ir.signals if not signal.is_memory}
    driving_lines = [
        f"{INDENT}{port.name} <= {ctx.name_for(port.name)};"
        for port in module_ir.ports
        if port.direction == "out" and port.name in signal_by_original
    ]
    if driving_lines:
        groups.append(driving_lines)

    lines: list[str] = []
    for index, group in enumerate(groups):
        if index > 0:
            lines.append("")
        lines.extend(group)
    return lines


def _render_assign(assign: vast.Assign, ctx) -> str:
    target_name = assign.left.var.name
    target = ctx.name_for(target_name)
    target_width = ctx.target_width_for(target_name)
    value = _render_assign_value(assign.right.var, target_width, ctx)
    return f"{INDENT}{target} <= {value};"


def _render_assign_value(rhs, target_width, ctx) -> str:
    # `SizedFIFO.v`'s `depthLess2 = p2depth2[p3cntr_width-1:0]` reinterprets
    # a natural-valued localparam's bits as a vector -- a Verilog idiom
    # with no VHDL equivalent through ordinary slicing, since a `natural`
    # cannot be indexed with `(msb downto lsb)`. `toSlv` is the same
    # elaboration-time conversion `_render_identifier` already applies to a
    # "natural"-kind parameter in a vector context; this is the one other
    # place in the corpus that same conversion is needed.
    if isinstance(rhs, vast.Partselect) and isinstance(rhs.var, vast.Identifier):
        localparam_name = ctx.localparam_name.get(rhs.var.name.lower())
        if localparam_name is not None:
            return f"toSlv({localparam_name}, {target_width})"
    return _expr.render_expression(rhs, ctx, target_width=target_width)


def _render_process(always_node, ctx) -> list[str]:
    clock_name = always_node.sens_list.list[0].sig.name
    lines = [
        f"{INDENT}process ({clock_name}) is",
        f"{INDENT}begin",
        f"{INDENT * 2}if rising_edge({clock_name}) then",
    ]
    lines.extend(_stmt.render_statement(always_node.statement, ctx, indent=3))
    lines.append(f"{INDENT * 2}end if;")
    lines.append(f"{INDENT}end process;")
    return lines
