# Test methodology:
# - Sweep: every continuous `assign` (top-level or embedded inside a
#   combined declaration-and-initializer, e.g. `wire [..] x = expr;`) and
#   every `always` block, in all thirteen vendored blue-lib `.v` files,
#   discovered by glob rather than enumerated by name so a fourteenth
#   vendored file is covered the moment it lands. `initial`-block content
#   is deliberately excluded: its power-on values are a separate pass
#   (`initializers.py`), not this plan's width/expression machinery, and
#   its one multi-bit replication idiom (`{((width+1)/2){2'b10}}`) is
#   exactly the shape `render_expression` refuses outside that path.
# - Stimulus: the real vendored corpus, parsed directly with pyverilog
#   (not through `parser.py`, which does not yet handle a top-level
#   continuous `assign` and is owned by a different plan in this same
#   wave), against a per-file context built from that file's own
#   parameter and port/reg/wire declarations.
# - Checks: every raised exception is collected with its file, line, and
#   node class before a single assertion fires, so one run reports every
#   verdict; the four named hard sites are pinned on their rendered text,
#   not just their width; a fourth check confirms the sweep raised zero
#   refusals across the whole corpus, the positive statement of the
#   census that motivated the whole plan.
# - Timing: None. This file launches no simulator.
from __future__ import annotations

import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import pyverilog.vparser.ast as vast
from pyverilog.vparser.parser import parse as _pyverilog_parse

from tools.bsc2vhdl.errors import UnsupportedConstruct
from tools.bsc2vhdl.expr import render_expression
from tools.bsc2vhdl.width import infer_width, symbolic_size, _node_to_text


@dataclass
class _Ctx:
    path: Path
    signal_size: dict = field(default_factory=dict)
    generic_name: dict = field(default_factory=dict)
    param_kind: dict = field(default_factory=dict)
    param_names: set = field(default_factory=set)

    def is_param(self, name: str) -> bool:
        return name in self.param_names

    def name_for(self, name: str) -> str:
        return name

    def target_width_for(self, name: str) -> str | None:
        return self.signal_size.get(name)


def _parse_raw(path: Path):
    ast_root, _directives = _pyverilog_parse(
        [str(path)], preprocess_define=[], debug=False, outputdir=tempfile.gettempdir()
    )
    return [item for item in ast_root.description.definitions if isinstance(item, vast.ModuleDef)][0]


def _collect(module_def):
    """Return every `Assign`, `Always`, and `Decl` node reachable from the
    module's items, wherever it actually lives. pyverilog sometimes embeds
    a continuous assign for a combined declaration-and-initializer
    (`wire [..] x = expr;`) inside the `Decl` node's own `.list` rather
    than as a sibling top-level item, so a plain top-level scan misses it;
    a full recursive walk does not."""
    assigns: list = []
    always_blocks: list = []
    decls: list = []

    def _walk(node) -> None:
        if isinstance(node, vast.Assign):
            assigns.append(node)
        elif isinstance(node, vast.Always):
            always_blocks.append(node)
        elif isinstance(node, vast.Decl):
            decls.append(node)
        for child in node.children():
            _walk(child)

    for item in module_def.items:
        _walk(item)
    return assigns, always_blocks, decls


def _width_bound_texts(decls) -> list[str]:
    texts: list[str] = []
    for decl_group in decls:
        for decl in decl_group.list:
            width = getattr(decl, "width", None)
            if width is not None:
                texts.append(_ast_dump_names(width.msb) + " " + _ast_dump_names(width.lsb))
    return texts


def _ast_dump_names(node) -> str:
    if isinstance(node, vast.Identifier):
        return node.name
    return " ".join(_ast_dump_names(child) for child in node.children())


def _build_ctx(path: Path, decls) -> _Ctx:
    ctx = _Ctx(path=path)
    for decl_group in decls:
        for decl in decl_group.list:
            if isinstance(decl, vast.Parameter):
                ctx.param_names.add(decl.name)
                ctx.generic_name[decl.name] = f"{decl.name.upper()}_G"
    width_texts = _width_bound_texts(decls)
    for decl_group in decls:
        for decl in decl_group.list:
            if isinstance(decl, (vast.Input, vast.Output, vast.Reg, vast.Wire)) and decl.width is not None:
                msb_text = _node_to_text(decl.width.msb, ctx)
                lsb_text = _node_to_text(decl.width.lsb, ctx)
                ctx.signal_size[decl.name] = symbolic_size(msb_text, lsb_text)
    for name in ctx.param_names:
        pattern = re.compile(rf"\b{re.escape(name)}\b")
        ctx.param_kind[name] = "positive" if any(pattern.search(text) for text in width_texts) else "natural"
    return ctx


def _collect_substitutions(statement):
    """Every blocking or nonblocking substitution reachable from `statement`,
    wherever it lives (including nested inside an `if`, `case`, or
    `casez`)."""
    result: list = []

    def _walk(node) -> None:
        if isinstance(node, (vast.BlockingSubstitution, vast.NonblockingSubstitution)):
            result.append(node)
        for child in node.children():
            _walk(child)

    _walk(statement)
    return result


def _sweep_file(path: Path) -> list[str]:
    """Infer and render every assign and every substitution reachable from
    an always block in `path`. Returns a list of failure descriptions;
    empty means every expression in this file resolved and rendered with
    no refusal.

    Substitution *targets* are read only by name when the target is a
    plain identifier (`Q_OUT <= ...`); a memory-element target
    (`RAM[ADDRA] <= ...`) has no single declared width in this plan's
    scope, so its assignment is exercised with `target_width=None` rather
    than guessed at -- memory-array element width is a later plan's
    concern, not this one's.
    """
    module_def = _parse_raw(path)
    assigns, always_blocks, decls = _collect(module_def)
    ctx = _build_ctx(path, decls)

    failures: list[str] = []
    for assign in assigns:
        lhs_name = getattr(assign.left.var, "name", None)
        target_width = ctx.signal_size.get(lhs_name) if lhs_name else None
        try:
            infer_width(assign.right.var, ctx)
            render_expression(assign.right.var, ctx, target_width=target_width)
        except UnsupportedConstruct as exc:
            failures.append(f"{path.name}: assign to {lhs_name}: {exc}")

    for always in always_blocks:
        for sub in _collect_substitutions(always.statement):
            lhs_name = getattr(sub.left.var, "name", None)
            target_width = ctx.signal_size.get(lhs_name) if lhs_name else None
            try:
                infer_width(sub.right.var, ctx)
                render_expression(sub.right.var, ctx, target_width=target_width)
            except UnsupportedConstruct as exc:
                failures.append(f"{path.name}: assignment to {lhs_name} at line {getattr(sub, 'lineno', 0)}: {exc}")

    return failures


def _vendor_files(vendor_dir: Path) -> list[Path]:
    files = sorted(vendor_dir.glob("*.v"))
    assert len(files) == 13, f"expected thirteen vendored Verilog files, found {len(files)}: {files}"
    return files


def test_corpus_every_expression_infers_a_width(vendor_dir: Path) -> None:
    all_failures: list[str] = []
    for path in _vendor_files(vendor_dir):
        all_failures.extend(_sweep_file(path))
    assert not all_failures, "\n".join(all_failures)


def test_corpus_no_forbidden_construct_slips_through(vendor_dir: Path) -> None:
    # The positive statement of the census result: this corpus contains no
    # shift, no signed or unsigned system function, no reduction operator,
    # no division, and no modulo, so the sweep above raises zero refusals.
    # If a future vendored file introduces one, `_sweep_file` names it.
    all_failures: list[str] = []
    for path in _vendor_files(vendor_dir):
        all_failures.extend(_sweep_file(path))
    assert all_failures == []


def test_corpus_known_hard_sites(vendor_dir: Path) -> None:
    _assert_fifo2_masked_or(vendor_dir)
    _assert_counter_three_term_sum(vendor_dir)
    _assert_sizedfifo_pointer_partselect(vendor_dir)
    _assert_bram2_pipelined_ternary(vendor_dir)


def _find_assign(module_def, lhs_name: str):
    assigns, _always, _decls = _collect(module_def)
    for assign in assigns:
        if getattr(assign.left.var, "name", None) == lhs_name:
            return assign
    raise AssertionError(f"no assign to {lhs_name!r} found")


def _find_nonblocking(module_def, lhs_name: str, rhs_type=None):
    """Return the nonblocking assignment to `lhs_name`. Several always
    blocks in this corpus assign the same target in more than one branch
    (a reset branch and a data branch); `rhs_type` disambiguates by the
    class of the assignment's right-hand side when more than one match
    exists."""
    matches = []

    def _walk(node) -> None:
        if isinstance(node, vast.NonblockingSubstitution) and getattr(node.left.var, "name", None) == lhs_name:
            matches.append(node)
        for child in node.children():
            _walk(child)

    for item in module_def.items:
        _walk(item)
    assert matches, f"no nonblocking assignment to {lhs_name!r} found"
    if rhs_type is None:
        return matches[0]
    for match in matches:
        if isinstance(match.right.var, rhs_type):
            return match
    raise AssertionError(f"no nonblocking assignment to {lhs_name!r} with a {rhs_type.__name__} right-hand side")


def _assert_fifo2_masked_or(vendor_dir: Path) -> None:
    path = vendor_dir / "FIFO2.v"
    module_def = _parse_raw(path)
    _assigns, _always, decls = _collect(module_def)
    ctx = _build_ctx(path, decls)
    node = _find_nonblocking(module_def, "data0_reg")
    target_width = ctx.signal_size.get("data0_reg")
    text = render_expression(node.right.var, ctx, target_width=target_width)
    assert text.count("slvAll(") == 3
    assert text.count(" or ") == 2


def _assert_counter_three_term_sum(vendor_dir: Path) -> None:
    path = vendor_dir / "Counter.v"
    module_def = _parse_raw(path)
    _assigns, _always, decls = _collect(module_def)
    ctx = _build_ctx(path, decls)
    node = _find_nonblocking(module_def, "q_state", rhs_type=vast.Plus)
    target_width = ctx.signal_size.get("q_state")
    text = render_expression(node.right.var, ctx, target_width=target_width)
    assert text.count("unsigned(") == 3
    assert "resize(" not in text, "operands already at the result width must not be widened again"


def _assert_sizedfifo_pointer_partselect(vendor_dir: Path) -> None:
    path = vendor_dir / "SizedFIFO.v"
    module_def = _parse_raw(path)
    _assigns, _always, decls = _collect(module_def)
    ctx = _build_ctx(path, decls)
    assign = _find_assign(module_def, "depthLess2")
    target_width = ctx.signal_size.get("depthLess2")
    text = render_expression(assign.right.var, ctx, target_width=target_width)
    assert "downto" in text
    assert "resize(" not in text, "an already-correct-width part-select must not also be resized"


def _assert_bram2_pipelined_ternary(vendor_dir: Path) -> None:
    path = vendor_dir / "BRAM2.v"
    module_def = _parse_raw(path)
    _assigns, _always, decls = _collect(module_def)
    ctx = _build_ctx(path, decls)
    assign = _find_assign(module_def, "DOA")
    target_width = ctx.signal_size.get("DOA")
    text = render_expression(assign.right.var, ctx, target_width=target_width)
    assert text.count("ite(") == 1
    assert "resize(" not in text, "both arms of the ternary must already render at the same width"
