"""Parses one Verilog module into a `ModuleIR`.

`parse_module` calls `pyverilog.vparser.parser.parse` with
`preprocess_define` explicitly the empty list so every `BSV_*` macro stays
undefined and each file's own `ifdef` fallback supplies active-low
synchronous reset and an empty assignment delay. There is no `-U`
mechanism in pyverilog's preprocessor and none is needed.

The default posture is refusal: any node class this walk does not
recognize raises `UnsupportedConstruct` naming the node class and its
line, including `GenerateStatement`, `inout` ports, and `TaskDef` even
before those become reachable from the actual corpus.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pyverilog.vparser.ast as vast
from pyverilog.vparser.parser import parse as _pyverilog_parse

from . import strip as _strip
from . import width as _width
from .errors import UnsupportedConstruct
from .ir import ModuleIR, ParamDecl, PortDecl, SignalDecl

_BINOP_TEXT = {
    vast.Plus: "+",
    vast.Minus: "-",
    vast.Times: "*",
    vast.Divide: "/",
}


def parse_module(path: Path) -> ModuleIR:
    path = Path(path)
    # `outputdir` keeps PLY's cached parser-table files (parser.out,
    # parsetab.py) out of whatever directory this process happens to be run
    # from; the tool has no default output directory of its own to write
    # them into, and neither of those files is transpiler output.
    ast_root, _directives = _pyverilog_parse(
        [str(path)], preprocess_define=[], debug=False, outputdir=tempfile.gettempdir()
    )

    module_defs = [item for item in ast_root.description.definitions if isinstance(item, vast.ModuleDef)]
    if len(module_defs) != 1:
        raise UnsupportedConstruct("source file with other than one module", path, 0)
    module_def = module_defs[0]

    params: list[ParamDecl] = []
    port_directions: dict[str, str] = {}
    port_widths: dict[str, tuple[str | None, str | None]] = {}
    signals: list[SignalDecl] = []
    always_blocks: list = []
    initials: list = []

    for item in module_def.items:
        if isinstance(item, vast.Decl):
            for decl in item.list:
                _handle_decl(decl, path, params, port_directions, port_widths, signals)
        elif isinstance(item, vast.Always):
            always_blocks.append(item)
        elif _strip.is_simulation_only(item):
            initials.append(item)
        else:
            raise UnsupportedConstruct(type(item).__name__, path, getattr(item, "lineno", 0))

    ports: list[PortDecl] = []
    for port in module_def.portlist.ports:
        name = port.name
        direction = port_directions.get(name)
        if direction is None:
            raise UnsupportedConstruct(f"port {name!r} never declared a direction", path, getattr(port, "lineno", 0))
        msb, lsb = port_widths.get(name, (None, None))
        ports.append(PortDecl(name=name, direction=direction, msb_expr=msb, lsb_expr=lsb, is_scalar=msb is None))

    return ModuleIR(
        name=module_def.name,
        source_path=path,
        params=tuple(params),
        ports=tuple(ports),
        signals=tuple(signals),
        always_blocks=tuple(always_blocks),
        initials=tuple(initials),
    )


def _handle_decl(decl, path, params, port_directions, port_widths, signals) -> None:
    if isinstance(decl, vast.Parameter):
        default_value = _param_default_value(decl, path)
        default_expr = _param_default_text(decl.value.var)
        params.append(ParamDecl(name=decl.name, default_expr=default_expr, default_value=default_value))
    elif isinstance(decl, vast.Localparam):
        raise UnsupportedConstruct("Localparam", path, getattr(decl, "lineno", 0))
    elif isinstance(decl, vast.Inout):
        raise UnsupportedConstruct("inout port", path, getattr(decl, "lineno", 0))
    elif isinstance(decl, vast.Output):
        port_directions[decl.name] = "out"
        port_widths[decl.name] = _width_bounds(decl.width, path)
    elif isinstance(decl, vast.Input):
        port_directions[decl.name] = "in"
        port_widths[decl.name] = _width_bounds(decl.width, path)
    elif isinstance(decl, vast.Reg):
        msb, lsb = _width_bounds(decl.width, path)
        signals.append(
            SignalDecl(
                name=decl.name,
                msb_expr=msb,
                lsb_expr=lsb,
                is_scalar=decl.width is None,
                is_memory=False,
                depth_expr=None,
            )
        )
    else:
        raise UnsupportedConstruct(type(decl).__name__, path, getattr(decl, "lineno", 0))


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
