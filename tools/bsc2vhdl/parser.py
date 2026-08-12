"""Parses one Verilog module into a `ModuleIR`.

`parse_module` calls `pyverilog.vparser.parser.parse` with
`preprocess_define` explicitly the empty list so every `BSV_*` macro stays
undefined and each file's own `ifdef` fallback supplies active-low
synchronous reset and an empty assignment delay. There is no `-U`
mechanism in pyverilog's preprocessor and none is needed.

The default posture is refusal: any node class this walk does not
recognize raises `UnsupportedConstruct` naming the node class and its
line, including `GenerateStatement`, `inout` ports, and `Task` even
before those become reachable from the actual corpus. Two shapes get an
explicit named check rather than relying on that generic fallback, because
letting them through silently would misbehave instead of erroring: a port
carrying a dimension list (an array-of-vectors port, which this walk's
width handling does not account for at all), and an `always` block whose
sensitivity list is anything other than a single `posedge` on one signal
(a mixed edge/level sensitivity list, which the emitter's synchronous
single-clock process shape cannot represent).

A top-level continuous `assign` (`vast.Assign`) is collected into
`ModuleIR.assigns` for `emit.py` to render as a concurrent VHDL signal
assignment. pyverilog surfaces a combined `wire ... = <expr>;` declaration
as a *separate* `Assign` node interleaved inside the same `Decl.list` as
the `Wire` node itself (the `Wire` node's own `.value` field stays `None`
even for this form), so `_handle_decl` collects an `Assign` found there the
same way the top-level item loop does. A `Wire` whose name is already a
port (the non-ANSI `output wire Q_OUT_1;` net-type redeclaration idiom)
adds no new signal at all: the port already carries its own identity
verbatim, and the continuous assign that actually drives it targets the
port name directly.

A `Localparam` is a *subclass* of `Parameter` in pyverilog's own class
hierarchy, so it must be checked before the `Parameter` branch or it is
silently swallowed by it. A localparam's value is rendered once, here, to
final VHDL text (generic names already substituted): unlike a width bound,
a localparam's value is never re-interpreted per use site, so there is
nothing for `width.py` to do with it downstream.

A top-level `InstanceList` (a module instantiation) is collected into
`ModuleIR.instances` as one `InstanceDecl` per instance. Every parameter
override must be a plain `IntConst` and every port association must be
either a plain `Identifier` or the Verilog `.portname()` open-port idiom
(`argname is None`, `mkAxisTransportLayer.v`'s two unconnected
`mkTransportLayer` outputs); anything else -- a part-select or an
expression as an actual -- is outside what `instantiate.py`'s naming rule
can derive a signature from and is refused by name, matching every other
refusal in this package. This is the one node class the tracer's own
top-level item loop never recognized at all: no file in the thirteen-file
blue-lib corpus instantiates anything, so nothing exercised this path
before the file that actually does (`mkAxisTransportLayer.v`).
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pyverilog.vparser.ast as vast
from pyverilog.vparser.parser import parse as _pyverilog_parse

from . import strip as _strip
from . import width as _width
from .errors import UnsupportedConstruct
from .ir import InstanceDecl, InstanceParam, InstancePort, LocalparamDecl, ModuleIR, ParamDecl, PortDecl, SignalDecl

_BINOP_TEXT = {
    vast.Plus: "+",
    vast.Minus: "-",
    vast.Times: "*",
    vast.Divide: "/",
}

_COMPARISON_TEXT = {
    vast.GreaterEq: ">=",
    vast.LessEq: "<=",
    vast.GreaterThan: ">",
    vast.LessThan: "<",
    vast.Eq: "=",
    vast.NotEq: "/=",
}


def _parse_ast(path: Path):
    # `outputdir` keeps PLY's cached parser-table files (parser.out,
    # parsetab.py) out of whatever directory this process happens to be run
    # from; the tool has no default output directory of its own to write
    # them into, and neither of those files is transpiler output.
    ast_root, _directives = _pyverilog_parse(
        [str(path)], preprocess_define=[], debug=False, outputdir=tempfile.gettempdir()
    )
    return ast_root


def _single_module_def(ast_root, path: Path):
    module_defs = [item for item in ast_root.description.definitions if isinstance(item, vast.ModuleDef)]
    if len(module_defs) != 1:
        raise UnsupportedConstruct("source file with other than one module", path, 0)
    return module_defs[0]


def _dispatch_item(
    item, path, params, localparams, port_directions, port_widths, signals, always_blocks, initials, assigns,
    instances,
) -> None:
    """Handle one top-level module item.

    Shared by `parse_module` (raise-on-first-refusal) and `survey_module`
    (collect-all-refusals): both walk `module_def.items` calling this once
    per item, differing only in whether a raised `UnsupportedConstruct`
    propagates or is caught by the caller so the walk continues.
    """
    if isinstance(item, vast.Decl):
        for decl in item.list:
            _handle_decl(decl, path, params, localparams, port_directions, port_widths, signals, assigns)
    elif isinstance(item, vast.Always):
        _check_always_sensitivity(item, path)
        always_blocks.append(item)
    elif isinstance(item, vast.Assign):
        assigns.append(item)
    elif isinstance(item, vast.InstanceList):
        instances.extend(_handle_instance_list(item, path))
    elif _strip.is_simulation_only(item):
        initials.append(item)
    else:
        raise UnsupportedConstruct(type(item).__name__, path, getattr(item, "lineno", 0))


def _dispatch_port(port, path, port_directions, port_widths) -> PortDecl:
    """Handle one port-list entry. Shared by `parse_module` and
    `survey_module` for the same reason `_dispatch_item` is."""
    if isinstance(port, vast.Ioport):
        raise UnsupportedConstruct("Ioport", path, getattr(port, "lineno", 0))
    if getattr(port, "dimensions", None) is not None:
        raise UnsupportedConstruct("port dimension list", path, getattr(port, "lineno", 0))
    name = port.name
    direction = port_directions.get(name)
    if direction is None:
        raise UnsupportedConstruct(f"port {name!r} never declared a direction", path, getattr(port, "lineno", 0))
    msb, lsb = port_widths.get(name, (None, None))
    return PortDecl(name=name, direction=direction, msb_expr=msb, lsb_expr=lsb, is_scalar=msb is None)


def parse_module(path: Path) -> ModuleIR:
    path = Path(path)
    module_def = _single_module_def(_parse_ast(path), path)

    params: list[ParamDecl] = []
    localparams: list[LocalparamDecl] = []
    port_directions: dict[str, str] = {}
    port_widths: dict[str, tuple[str | None, str | None]] = {}
    signals: list[SignalDecl] = []
    always_blocks: list = []
    initials: list = []
    assigns: list = []
    instances: list = []

    for item in module_def.items:
        _dispatch_item(
            item, path, params, localparams, port_directions, port_widths, signals, always_blocks, initials,
            assigns, instances,
        )

    ports: list[PortDecl] = []
    for port in module_def.portlist.ports:
        ports.append(_dispatch_port(port, path, port_directions, port_widths))

    return ModuleIR(
        name=module_def.name,
        source_path=path,
        params=tuple(params),
        ports=tuple(ports),
        signals=tuple(signals),
        localparams=tuple(localparams),
        assigns=tuple(assigns),
        always_blocks=tuple(always_blocks),
        initials=tuple(initials),
        instances=tuple(instances),
    )


def survey_module(path: Path) -> list[UnsupportedConstruct]:
    """Walk `path` collecting every out-of-subset construct instead of
    raising on the first one.

    Performs the same pyverilog parse `parse_module` performs, then calls
    the same per-item dispatch (`_dispatch_item`) over the module's
    top-level items and the same per-port dispatch (`_dispatch_port`) over
    its port list, catching `UnsupportedConstruct` at each call and moving
    on to the next item or port rather than propagating it. One refusing
    item must not hide refusals in later items: that is the entire point of
    a census. Refusals are returned in source order, exactly as
    encountered, with no deduplication and no sorting.

    A refusal raised below item granularity (inside `_render_expr`,
    `_param_default_value`, and similar helpers `_dispatch_item` calls into)
    is attributed to the enclosing top-level item's own line, which is
    accurate enough for a census.

    `parse_module`'s hard-fail contract is untouched by this function: this
    is a second, additive entry point, not a collect-versus-raise flag
    threaded through the first.
    """
    path = Path(path)
    ast_root = _parse_ast(path)

    module_defs = [item for item in ast_root.description.definitions if isinstance(item, vast.ModuleDef)]
    if len(module_defs) != 1:
        return [UnsupportedConstruct("source file with other than one module", path, 0)]
    module_def = module_defs[0]

    refusals: list[UnsupportedConstruct] = []
    params: list[ParamDecl] = []
    localparams: list[LocalparamDecl] = []
    port_directions: dict[str, str] = {}
    port_widths: dict[str, tuple[str | None, str | None]] = {}
    signals: list[SignalDecl] = []
    always_blocks: list = []
    initials: list = []
    assigns: list = []
    instances: list = []

    for item in module_def.items:
        try:
            _dispatch_item(
                item, path, params, localparams, port_directions, port_widths, signals, always_blocks, initials,
                assigns, instances,
            )
        except UnsupportedConstruct as exc:
            refusals.append(exc)

    for port in module_def.portlist.ports:
        try:
            _dispatch_port(port, path, port_directions, port_widths)
        except UnsupportedConstruct as exc:
            refusals.append(exc)

    return refusals


def _handle_instance_list(item, path) -> list[InstanceDecl]:
    result: list[InstanceDecl] = []
    for inst in item.instances:
        params: list[InstanceParam] = []
        for parg in inst.parameterlist:
            value_node = parg.argname
            if not isinstance(value_node, vast.IntConst):
                raise UnsupportedConstruct(
                    "non-constant instance parameter override", path, getattr(inst, "lineno", 0)
                )
            params.append(
                InstanceParam(
                    name=parg.paramname,
                    value_expr=value_node.value,
                    value=_width.parse_int_literal(value_node.value),
                )
            )
        ports: list[InstancePort] = []
        for parg in inst.portlist:
            actual = parg.argname
            if actual is None:
                ports.append(InstancePort(name=parg.portname, actual_expr=None))
            elif isinstance(actual, vast.Identifier):
                ports.append(InstancePort(name=parg.portname, actual_expr=actual.name))
            else:
                raise UnsupportedConstruct(
                    "non-identifier instance port connection", path, getattr(inst, "lineno", 0)
                )
        result.append(InstanceDecl(module=inst.module, name=inst.name, params=tuple(params), ports=tuple(ports)))
    return result


def _handle_decl(decl, path, params, localparams, port_directions, port_widths, signals, assigns) -> None:
    if isinstance(decl, vast.Localparam):
        value_expr = _render_localparam_value(decl.value.var, path)
        localparams.append(LocalparamDecl(name=decl.name, value_expr=value_expr))
    elif isinstance(decl, vast.Parameter):
        default_value = _param_default_value(decl, path)
        default_expr = _param_default_text(decl.value.var)
        params.append(ParamDecl(name=decl.name, default_expr=default_expr, default_value=default_value))
    elif isinstance(decl, vast.Inout):
        raise UnsupportedConstruct("inout port", path, getattr(decl, "lineno", 0))
    elif isinstance(decl, vast.Output):
        if getattr(decl, "dimensions", None) is not None:
            raise UnsupportedConstruct("port dimension list", path, getattr(decl, "lineno", 0))
        port_directions[decl.name] = "out"
        port_widths[decl.name] = _width_bounds(decl.width, path)
    elif isinstance(decl, vast.Input):
        if getattr(decl, "dimensions", None) is not None:
            raise UnsupportedConstruct("port dimension list", path, getattr(decl, "lineno", 0))
        port_directions[decl.name] = "in"
        port_widths[decl.name] = _width_bounds(decl.width, path)
    elif isinstance(decl, vast.Reg):
        msb, lsb = _width_bounds(decl.width, path)
        dimensions = getattr(decl, "dimensions", None)
        if dimensions is not None:
            depth_low, depth_high = _memory_bounds(dimensions, path)
            signals.append(
                SignalDecl(
                    name=decl.name,
                    msb_expr=msb,
                    lsb_expr=lsb,
                    is_scalar=decl.width is None,
                    is_memory=True,
                    depth_low_expr=depth_low,
                    depth_high_expr=depth_high,
                )
            )
        else:
            signals.append(
                SignalDecl(name=decl.name, msb_expr=msb, lsb_expr=lsb, is_scalar=decl.width is None, is_memory=False)
            )
    elif isinstance(decl, vast.Wire):
        # The non-ANSI `output wire Q_OUT_1;` idiom redeclares an
        # already-declared port's net type; it introduces no new signal at
        # all, since the port itself already carries the identity that a
        # continuous assign to it will target verbatim (D-14).
        if decl.name in port_directions:
            return
        if getattr(decl, "dimensions", None) is not None:
            raise UnsupportedConstruct("memory-shaped wire declaration", path, getattr(decl, "lineno", 0))
        msb, lsb = _width_bounds(decl.width, path)
        signals.append(
            SignalDecl(name=decl.name, msb_expr=msb, lsb_expr=lsb, is_scalar=decl.width is None, is_memory=False)
        )
    elif isinstance(decl, vast.Assign):
        # pyverilog's own representation of `wire ... = <expr>;`: a bare
        # `Assign` node sitting in the same `Decl.list` as the `Wire`
        # declaration it initializes, never in the `Wire` node's own
        # `.value` field.
        assigns.append(decl)
    elif isinstance(decl, vast.Integer):
        # A simulation-only loop or scratch variable (`integer i;`) declared
        # at module scope for use inside an `initial` block. `strip.py`
        # already drops the block that declares and uses it; the
        # declaration itself carries no synthesizable meaning.
        return
    else:
        raise UnsupportedConstruct(type(decl).__name__, path, getattr(decl, "lineno", 0))


def _memory_bounds(dimensions, path) -> tuple[str, str]:
    if len(dimensions.lengths) != 1:
        raise UnsupportedConstruct(
            "multi-dimensional memory array", path, getattr(dimensions, "lineno", 0)
        )
    length = dimensions.lengths[0]
    return _render_expr(length.msb, path), _render_expr(length.lsb, path)


def _render_localparam_value(node, path) -> str:
    """Render a localparam's value expression as final VHDL text.

    Unlike a width bound (`_render_expr`, below), the result here has
    already had every parameter name mapped to its generic name
    (`f"{name.upper()}_G"`, the same rule `emit.py`/`width.py` apply
    independently), because a localparam's own VHDL constant declaration is
    self-contained: nothing downstream re-derives it per use site.
    """
    if isinstance(node, vast.Cond):
        cond_text = _render_localparam_condition(node.cond, path)
        true_text = _render_localparam_value(node.true_value, path)
        false_text = _render_localparam_value(node.false_value, path)
        return f"ite({cond_text}, {true_text}, {false_text})"
    return _render_localparam_operand(node, path)


def _render_localparam_operand(node, path) -> str:
    if isinstance(node, vast.IntConst):
        return str(_width.parse_int_literal(node.value))
    if isinstance(node, vast.Identifier):
        return f"{node.name.upper()}_G"
    if isinstance(node, vast.Uminus):
        return f"-{_render_localparam_operand(node.right, path)}"
    if isinstance(node, vast.Uplus):
        return _render_localparam_operand(node.right, path)
    for cls, op in _BINOP_TEXT.items():
        if isinstance(node, cls):
            return f"{_render_localparam_operand(node.left, path)} {op} {_render_localparam_operand(node.right, path)}"
    raise UnsupportedConstruct(type(node).__name__ + " localparam value", path, getattr(node, "lineno", 0))


def _render_localparam_condition(node, path) -> str:
    for cls, op in _COMPARISON_TEXT.items():
        if isinstance(node, cls):
            left = _render_localparam_operand(node.left, path)
            right = _render_localparam_operand(node.right, path)
            return f"{left} {op} {right}"
    raise UnsupportedConstruct(type(node).__name__ + " localparam condition", path, getattr(node, "lineno", 0))


def _check_always_sensitivity(always_node, path) -> None:
    """Refuse an `always` block whose sensitivity list is not a single
    `posedge` (a clocked process) or a single `level` item on one signal (a
    combinational process, BSC's own idiom for a multiplexer with no
    ordinary continuous-assign shape -- `mkAxisTransportLayer.v`'s sole
    `always@(one_signal) case (...) ...` block takes this form).

    The emitter's clocked process shape (`process (CLK) is ... if
    rising_edge(CLK) then ...`) is single-clock, edge-triggered by
    construction; a combinational process has no such wrapper at all
    (`emit.py`'s `_render_process` branches on this same `sens.type`). A
    mixed edge/level list, more than one sensitivity item, or any edge
    other than `posedge`/`level` has no VHDL translation either shape can
    produce.
    """
    sens_items = always_node.sens_list.list
    if len(sens_items) != 1:
        raise UnsupportedConstruct(
            "always block with more than one sensitivity item", path, getattr(always_node, "lineno", 0)
        )
    sens = sens_items[0]
    if sens.type not in ("posedge", "level"):
        raise UnsupportedConstruct(
            f"always block sensitivity edge {sens.type!r}", path, getattr(always_node, "lineno", 0)
        )


def _width_bounds(width_node, path) -> tuple[str | None, str | None]:
    if width_node is None:
        return None, None
    return _render_expr(width_node.msb, path), _render_expr(width_node.lsb, path)


def _render_expr(node, path) -> str:
    if isinstance(node, vast.IntConst):
        return str(_width.parse_int_literal(node.value))
    if isinstance(node, vast.Identifier):
        return node.name
    if isinstance(node, vast.Uminus):
        return f"-{_render_expr(node.right, path)}"
    if isinstance(node, vast.Uplus):
        return _render_expr(node.right, path)
    for cls, op in _BINOP_TEXT.items():
        if isinstance(node, cls):
            return f"{_render_expr(node.left, path)} {op} {_render_expr(node.right, path)}"
    raise UnsupportedConstruct(type(node).__name__ + " width bound", path, getattr(node, "lineno", 0))


def _param_default_value(param: vast.Parameter, path) -> int:
    node = param.value.var
    if isinstance(node, vast.IntConst):
        return _width.parse_int_literal(node.value)
    if isinstance(node, vast.Repeat):
        concat = node.value
        if isinstance(concat, vast.Concat) and len(concat.list) == 1 and isinstance(concat.list[0], vast.IntConst):
            literal_value = _width.parse_int_literal(concat.list[0].value)
            if literal_value == 0:
                return 0
        raise UnsupportedConstruct(
            "non-zero replication parameter default", path, getattr(param, "lineno", 0)
        )
    raise UnsupportedConstruct(
        type(node).__name__ + " parameter default", path, getattr(param, "lineno", 0)
    )


def _param_default_text(node) -> str:
    if isinstance(node, vast.IntConst):
        return node.value
    if isinstance(node, vast.Repeat):
        concat = node.value
        count = node.times
        count_text = count.name if isinstance(count, vast.Identifier) else "?"
        inner = ",".join(item.value if isinstance(item, vast.IntConst) else "?" for item in concat.list)
        return f"{{{count_text}{{{inner}}}}}"
    return "?"
