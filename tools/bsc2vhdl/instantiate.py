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


def _scalar_bridges(module_ir) -> dict[tuple[str, str], tuple[str, str]]:
    """Every (instance name, formal port name) whose own actual disagrees
    with the component's shared signature, mapped to `(direction,
    bridge_signal_name)`.

    BSC sometimes declares a functionally identical port as a bare scalar
    wire at one instantiation site and as an explicit range at another
    (`FIFO2`'s `D_IN`/`D_OUT` are always `slv(WIDTH_G-1 downto 0)` on the
    real hand-written entity, never scalar, yet a handful of `mkQP.v`
    instances connect a bare one-bit wire to it). The component's own
    signature is derived once per (module, port) from whichever instance
    connects it first (`_port_signature`, the same rule
    `component_declarations` uses), so a *later* instance whose actual is
    scalar disagrees with that shared signature.

    Neither direction can bridge the mismatch with a plain type
    conversion at the association itself: an aggregate actual
    (`(0 => scalar)`) is a legal `in` association but not an `out` one --
    VHDL classifies a bare aggregate as an expression, and only `in`
    accepts an expression actual -- so both directions go through one
    `slv(0 downto 0)` bridge signal, connected to the formal directly (a
    plain name, legal either direction) and reconciled with the scalar
    through one extra concurrent assignment (`_bridge_assignment`) instead.
    """
    by_module: dict[str, list] = {}
    for instance in module_ir.instances:
        by_module.setdefault(instance.module, []).append(instance)
    driven_names = _driven_names(module_ir)

    vector_ports: set[tuple[str, str]] = set()
    for module_name, instances in by_module.items():
        seen_ports: set[str] = set()
        for instance in instances:
            for port in instance.ports:
                if port.name in seen_ports:
                    continue
                seen_ports.add(port.name)
                used_as_width: set[str] = set()
                _direction, type_text = _port_signature(port.name, instances, module_ir, driven_names, used_as_width)
                if type_text != "sl":
                    vector_ports.add((module_name, port.name))

    bridges: dict[tuple[str, str], tuple[str, str]] = {}
    for instance in module_ir.instances:
        for port in instance.ports:
            if port.actual_expr is None:
                continue
            if (instance.module, port.name) not in vector_ports:
                continue
            is_scalar, _msb, _lsb = _actual_shape(port.actual_expr, module_ir)
            if not is_scalar:
                continue
            direction = "in" if port.actual_expr in driven_names else "out"
            bridge_name = f"{instance.name}{port.name}Bridge"
            bridges[(instance.name, port.name)] = (direction, bridge_name)
    return bridges


def bridge_signal_declarations(module_ir) -> list[str]:
    """One `slv(0 downto 0)` declaration per `_scalar_bridges` entry, for
    the architecture's declarative part."""
    bridges = _scalar_bridges(module_ir)
    return [f"{INDENT}signal {bridge_name} : slv(0 downto 0);" for _direction, bridge_name in bridges.values()]


def bridge_assignments(module_ir, ctx) -> list[str]:
    """One concurrent assignment per `_scalar_bridges` entry, reconciling
    the bridge signal with the scalar actual it stands in for: the scalar
    drives bit 0 of the bridge on `in`, and reads bit 0 of the bridge on
    `out`."""
    bridges = _scalar_bridges(module_ir)
    lines: list[str] = []
    for instance in module_ir.instances:
        for port in instance.ports:
            key = (instance.name, port.name)
            if key not in bridges:
                continue
            direction, bridge_name = bridges[key]
            actual_text = ctx.name_for(port.actual_expr)
            if direction == "in":
                lines.append(f"{INDENT}{bridge_name} <= (0 => {actual_text});")
            else:
                lines.append(f"{INDENT}{actual_text} <= {bridge_name}(0);")
    return lines


def instantiations(module_ir, ctx) -> list[str]:
    if not module_ir.instances:
        return []

    bridges = _scalar_bridges(module_ir)

    lines: list[str] = []
    for index, instance in enumerate(module_ir.instances):
        if index > 0:
            lines.append("")
        lines.extend(_render_instantiation(instance, ctx, bridges))
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
        # accepted-risk note. `_render_component` may override this default
        # afterward, from an A/B-paired sibling port that *is* connected
        # (BRAM2's `DOA`, left open at mkQP.v:7592 because the generated
        # core only ever reads `DOB`, is the corpus's first port this
        # matters for).
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


def _has_connected_actual(port_name: str, instances: list) -> bool:
    return any(
        port.name == port_name and port.actual_expr is not None
        for instance in instances
        for port in instance.ports
    )


def _paired_sibling_name(port_name: str) -> str | None:
    """The A/B-paired counterpart of a dual-port-memory-shaped port name
    (`DOA`<->`DOB`, `ADDRA`<->`ADDRB`, `ENA`<->`ENB`, ...), or `None` if
    `port_name` does not end in a bare `A`/`B` suffix at all. Every one of
    BRAM2's own eight ports follows this convention."""
    if port_name.endswith("A"):
        return f"{port_name[:-1]}B"
    if port_name.endswith("B"):
        return f"{port_name[:-1]}A"
    return None


def _render_component(module_name: str, instances: list, module_ir, driven_names: set[str]) -> list[str]:
    used_as_width: set[str] = set()

    port_names: list[str] = []
    seen_ports: set[str] = set()
    for instance in instances:
        for port in instance.ports:
            if port.name not in seen_ports:
                seen_ports.add(port.name)
                port_names.append(port.name)

    signatures: dict[str, tuple[str, str]] = {
        port_name: _port_signature(port_name, instances, module_ir, driven_names, used_as_width)
        for port_name in port_names
    }

    # A port left unconnected on every instance of this module (the
    # `connected is None` fallback inside `_port_signature`, always
    # `("out", "sl")`) is only correct when the real entity actually is
    # scalar there. When an A/B-paired sibling port name *is* connected and
    # resolved to a non-scalar shape, that shape almost certainly applies
    # here too (a dual-port memory's two data, address, or enable ports
    # share the same width by construction), and a scalar default would
    # otherwise surface only as a GHDL elaboration-time port-binding
    # mismatch against the real hand-written entity, never inside this
    # transpiler (see the module docstring's accepted-risk note). This is
    # still derived entirely from the instantiation site -- the sibling's
    # own shape came from a connected actual elsewhere in this same file --
    # never from reading a `.vhd` file or a manifest.
    for port_name in port_names:
        direction, type_text = signatures[port_name]
        if type_text != "sl" or _has_connected_actual(port_name, instances):
            continue
        sibling_name = _paired_sibling_name(port_name)
        if sibling_name is None or sibling_name not in signatures:
            continue
        sibling_direction, sibling_type = signatures[sibling_name]
        if sibling_type == "sl" or sibling_direction != direction:
            continue
        signatures[port_name] = (direction, sibling_type)

    port_entries = [(port_name, *signatures[port_name]) for port_name in port_names]

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
    lines = [f"{INDENT * 2}generic ("]
    for index, (name, kind) in enumerate(entries):
        terminator = ");" if index == len(entries) - 1 else ";"
        # `kind` is never left-padded: it is the last token on the line
        # before `terminator`, exactly like `type_text` in
        # `_render_component_port_clause` below, so a mixed
        # `natural`/`positive` group (BRAM2's own four generics, the first
        # component in the corpus to need more than one) never leaves a
        # trailing space before `;`/`);`.
        lines.append(f"{INDENT * 3}{name.ljust(max_name + 1)}: {kind}{terminator}")
    return lines


def _render_component_port_clause(port_entries: list) -> list[str]:
    max_name = max(len(name) for name, _, _ in port_entries)
    max_dir = max(len(direction) for _, direction, _ in port_entries)
    lines = [f"{INDENT * 2}port ("]
    for index, (name, direction, type_text) in enumerate(port_entries):
        terminator = ");" if index == len(port_entries) - 1 else ";"
        lines.append(f"{INDENT * 3}{name.ljust(max_name + 1)}: {direction.ljust(max_dir)} {type_text}{terminator}")
    return lines


def _render_instantiation(instance, ctx, bridges) -> list[str]:
    lines = [f"{INDENT}{instance.name} : {instance.module}"]
    lines.extend(_render_generic_map(instance))
    lines.extend(_render_port_map(instance, ctx, bridges))
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


def _render_port_map(instance, ctx, bridges) -> list[str]:
    entries = []
    for port in instance.ports:
        if port.actual_expr is None:
            entries.append((port.name, "open"))
            continue
        key = (instance.name, port.name)
        if key in bridges:
            # This instance's own actual is a bare scalar wire, but the
            # component's shared signature (derived from a *different*
            # instance's vector-shaped actual) declares this formal as
            # `slv(...)`. The formal connects to the dedicated bridge
            # signal (a plain name, legal for either direction) instead of
            # the scalar directly; `bridge_assignments` reconciles the two.
            _direction, bridge_name = bridges[key]
            entries.append((port.name, bridge_name))
            continue
        entries.append((port.name, ctx.name_for(port.actual_expr)))
    max_name = max(len(name) for name, _ in entries)
    lines = [f"{INDENT * 2}port map ("]
    for index, (name, actual) in enumerate(entries):
        terminator = ");" if index == len(entries) - 1 else ","
        lines.append(f"{INDENT * 3}{name.ljust(max_name)} => {actual}{terminator}")
    return lines
