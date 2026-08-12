"""Cross-module reference emission: VHDL `component` declarations, plus a
plain instantiation for each, never `entity work.X` or `entity surf.X`.

GHDL analyzes a `component`-declared but never analyzed unit with exit 0
while a direct entity reference to a nonexistent unit fails with exit 1
(verified directly against this environment's GHDL). Since `mkAxisTransport
Layer.v` instantiates `mkTransportLayer`, a module with no VHDL at all yet,
this rule is applied uniformly to every cross-module reference this
emitter writes -- including `FIFO2`, which already has hand-written VHDL --
so the emission logic carries no hidden dependency on which other files
happen to exist in the library search path.

The referenced module's VHDL signature (its generics and its ports' names,
directions, and widths) is derived by rule from the instantiation site
itself, never by reading a `.vhd` file and never from a manifest:

  - A generic is named by uppercasing the Verilog parameter name and
    appending `_G`, exactly `emit.py`'s own rule for the *referencing*
    module's own parameters. `guarded` is on an explicit drop list (below):
    it has no effect on any output port anywhere in blue-lib, since it is
    read only inside the `$display`-guarded error-reporting block this
    tool's `strip.py` already drops, and every hand-written blue-lib entity
    already establishes the precedent of dropping it rather than carrying
    it through.
  - A port's own name and mode pass through verbatim. Mode is derived from
    a structural fact this one file already contains: an actual signal
    that is either a top-level input port of the *referencing* module, or
    the target of a continuous `assign` or an `always`-block assignment
    anywhere else in it, is already driven from outside this instance, so
    the connected formal must be `in`. An actual that is never driven by
    anything else in the file must be driven *by* this instance instead,
    so the formal is `out`. A formal left connected to nothing at all
    (`.portname()`, the open-port idiom) defaults to a scalar `out`: BSC
    only ever leaves a method's *result* unconnected when the caller does
    not need it, never an input, since an unconnected input would leave the
    referenced module functionally undriven.
  - A vector port's width is expressed symbolically through a generic
    exactly when this instance's own override of some surviving parameter
    equals the connected actual's own declared width; otherwise it falls
    back to that actual's own literal bounds (the only shape
    `mkTransportLayer` needs, since it declares zero parameters here and
    therefore gets no generic clause at all).

Accepted risk, matching D-04: if a hand-written entity's real signature
ever deviates from this rule, the mismatch surfaces as a GHDL binding
error once that entity is actually elaborated against, in a later phase,
never inside this transpiler. A signature manifest could be layered on
then without touching this module's own derivation logic.
"""
from __future__ import annotations

from . import strip as _strip
from .errors import UnsupportedConstruct

INDENT = "   "

# `guarded` has no effect on any output port anywhere in the corpus: every
# reference to it lives inside the `$display`-guarded error-reporting block
# `strip.py` already drops. Every hand-written blue-lib entity already
# established the precedent of dropping it from its own generic clause
# rather than carrying through a generic with no referent anywhere in the
# surviving code; this list applies that same precedent to a *referenced*
# module's own derived generic clause.
_DROPPED_PARAM_NAMES = frozenset({"guarded"})


def component_declarations(module_ir, ctx) -> list[str]:
    if not module_ir.instances:
        return []

    by_module: dict[str, list] = {}
    for instance in module_ir.instances:
        by_module.setdefault(instance.module, []).append(instance)

    driven_names = _driven_names(module_ir)

    lines: list[str] = []
    for index, module_name in enumerate(sorted(by_module)):
        if index > 0:
            lines.append("")
        lines.extend(_render_component(module_name, by_module[module_name], module_ir, driven_names))
    return lines


def instantiations(module_ir, ctx) -> list[str]:
    if not module_ir.instances:
        return []

    lines: list[str] = []
    for index, instance in enumerate(module_ir.instances):
        if index > 0:
            lines.append("")
        lines.extend(_render_instantiation(instance, ctx))
    return lines


def dropped_parameter_overrides(module_ir) -> dict[str, str]:
    """Every instance parameter override this file's naming rule drops.

    Keyed `"<instance>.<param>"`, so the emitted VHDL carrying no trace of
    a dropped `guarded` override is still visible somewhere -- the whole
    point of writing it into the name-map sidecar rather than discarding it
    in memory with nothing left to show it was ever there.
    """
    result: dict[str, str] = {}
    for instance in module_ir.instances:
        for param in instance.params:
            if param.name.lower() in _DROPPED_PARAM_NAMES:
                result[f"{instance.name}.{param.name}"] = "dropped: no generic emitted (guarded parameter)"
    return result


def _driven_names(module_ir) -> set[str]:
    """Names the referencing module's own logic drives, independent of any
    instantiation this module writes: a module input port (driven from
    outside, which counts as already driven for the purpose of deciding an
    instantiated port's own direction), a continuous `assign` target, or an
    `always`-block assignment target."""
    driven: set[str] = {port.name for port in module_ir.ports if port.direction == "in"}
    for assign in module_ir.assigns:
        target = _strip._assignment_target_name(assign.left.var)
        if target is not None:
            driven.add(target)
    for always_block in module_ir.always_blocks:
        driven |= _strip._assignment_targets(always_block.statement)
    return driven


def _actual_shape(name: str, module_ir) -> tuple[bool, str | None, str | None]:
    for port in module_ir.ports:
        if port.name == name:
            return port.is_scalar, port.msb_expr, port.lsb_expr
    for signal in module_ir.signals:
        if signal.name == name:
            return signal.is_scalar, signal.msb_expr, signal.lsb_expr
    raise UnsupportedConstruct(
        f"instantiation port connects to undeclared name {name!r}", module_ir.source_path, 0
    )


def _port_signature(
    port_name: str,
    instances: list,
    module_ir,
    driven_names: set[str],
    used_as_width: set[str],
) -> tuple[str, str]:
    """Derive one formal port's `(direction, vhdl_type_text)`.

    Looks at exactly one instance -- the first, in source order, that
    actually connects `port_name` to something -- never a majority vote
    across every instance of the same module: the component declaration is
    one signature shared by every instance, and the first connected
    occurrence is all the information this one file offers about it.
    """
    connected = None
    owning_instance = None
    for instance in instances:
        for port in instance.ports:
            if port.name == port_name and port.actual_expr is not None:
                connected = port
                owning_instance = instance
                break
        if connected is not None:
            break

    if connected is None:
        # Left unconnected in every instantiation of this module: BSC only
        # ever leaves a method *result* unconnected, never an input, so
        # this defaults to a scalar `out`. See the module docstring's
        # accepted-risk note.
        return "out", "sl"

    actual_name = connected.actual_expr
    direction = "in" if actual_name in driven_names else "out"

    is_scalar, msb_expr, lsb_expr = _actual_shape(actual_name, module_ir)
    if is_scalar:
        return direction, "sl"

    for param in owning_instance.params:
        if param.name.lower() in _DROPPED_PARAM_NAMES:
            continue
        if lsb_expr == "0" and msb_expr is not None and msb_expr.isdigit() and int(msb_expr) == param.value - 1:
            used_as_width.add(param.name)
            return direction, f"slv({param.name.upper()}_G-1 downto 0)"

    return direction, f"slv({msb_expr} downto {lsb_expr})"


def _render_component(module_name: str, instances: list, module_ir, driven_names: set[str]) -> list[str]:
    used_as_width: set[str] = set()

    port_names: list[str] = []
    seen_ports: set[str] = set()
    for instance in instances:
        for port in instance.ports:
            if port.name not in seen_ports:
                seen_ports.add(port.name)
                port_names.append(port.name)

    port_entries = [
        (port_name, *_port_signature(port_name, instances, module_ir, driven_names, used_as_width))
        for port_name in port_names
    ]

    param_names: list[str] = []
    seen_params: set[str] = set()
    for instance in instances:
        for param in instance.params:
            if param.name.lower() in _DROPPED_PARAM_NAMES or param.name in seen_params:
                continue
            seen_params.add(param.name)
            param_names.append(param.name)

    lines = [f"{INDENT}component {module_name} is"]
    if param_names:
        lines.extend(_render_component_generic_clause(param_names, used_as_width))
    lines.extend(_render_component_port_clause(port_entries))
    lines.append(f"{INDENT}end component;")
    return lines


def _render_component_generic_clause(param_names: list[str], used_as_width: set[str]) -> list[str]:
    entries = [(f"{name.upper()}_G", "positive" if name in used_as_width else "natural") for name in param_names]
    max_name = max(len(name) for name, _ in entries)
    max_kind = max(len(kind) for _, kind in entries)
    lines = [f"{INDENT * 2}generic ("]
    for index, (name, kind) in enumerate(entries):
        terminator = ");" if index == len(entries) - 1 else ";"
        lines.append(f"{INDENT * 3}{name.ljust(max_name + 1)}: {kind.ljust(max_kind)}{terminator}")
    return lines


def _render_component_port_clause(port_entries: list) -> list[str]:
    max_name = max(len(name) for name, _, _ in port_entries)
    max_dir = max(len(direction) for _, direction, _ in port_entries)
    lines = [f"{INDENT * 2}port ("]
    for index, (name, direction, type_text) in enumerate(port_entries):
        terminator = ");" if index == len(port_entries) - 1 else ";"
        lines.append(f"{INDENT * 3}{name.ljust(max_name + 1)}: {direction.ljust(max_dir)} {type_text}{terminator}")
    return lines


def _render_instantiation(instance, ctx) -> list[str]:
    lines = [f"{INDENT}{instance.name} : {instance.module}"]
    lines.extend(_render_generic_map(instance))
    lines.extend(_render_port_map(instance, ctx))
    return lines


def _render_generic_map(instance) -> list[str]:
    entries = [
        (f"{param.name.upper()}_G", str(param.value))
        for param in instance.params
        if param.name.lower() not in _DROPPED_PARAM_NAMES
    ]
    if not entries:
        return []
    max_name = max(len(name) for name, _ in entries)
    lines = [f"{INDENT * 2}generic map ("]
    for index, (name, value) in enumerate(entries):
        terminator = ")" if index == len(entries) - 1 else ","
        lines.append(f"{INDENT * 3}{name.ljust(max_name)} => {value}{terminator}")
    return lines


def _render_port_map(instance, ctx) -> list[str]:
    entries = [
        (port.name, "open" if port.actual_expr is None else ctx.name_for(port.actual_expr))
        for port in instance.ports
    ]
    max_name = max(len(name) for name, _ in entries)
    lines = [f"{INDENT * 2}port map ("]
    for index, (name, actual) in enumerate(entries):
        terminator = ");" if index == len(entries) - 1 else ","
        lines.append(f"{INDENT * 3}{name.ljust(max_name)} => {actual}{terminator}")
    return lines
