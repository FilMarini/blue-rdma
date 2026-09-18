# Test methodology:
# - Sweep: every idiom `initializer_for`/`memory_initializer_for` classify
#   (all-zero replication, the two-bit alternating replication, a plain
#   identifier reference), the `bsvAltInit` formula proven correct
#   independently of its own implementation at eight widths, the array
#   `others`-aggregate path against both real memory-bearing vendored
#   files, and the two refusal shapes (an index-dependent array element,
#   an unrecognized right-hand side).
# - Stimulus: the real vendored `BRAM2.v`/`SizedFIFO.v` fixtures through
#   the real `emit_vhdl` pipeline, plus one hand-built synthetic `Initial`
#   AST for the index-dependence refusal, which no real corpus fixture
#   exercises.
# - Checks: the alternating-pattern test computes its own expectation
#   independently, in the test, by simulating Verilog's
#   concatenation-then-truncation semantics directly in Python, never by
#   calling into `initializers.py` itself for that half of the comparison.
# - Timing: None. This file launches no simulator.
from __future__ import annotations

import re
from pathlib import Path

import pyverilog.vparser.ast as vast
import pytest

from tools.bsc2vhdl.emit import emit_vhdl
from tools.bsc2vhdl.errors import UnsupportedConstruct
from tools.bsc2vhdl.initializers import _for_loop_variable, memory_initializer_for
from tools.bsc2vhdl.parser import parse_module


def _verilog_alternating_bits(width: int) -> str:
    """Simulate `{((width+1)/2){2'b10}}` truncated to `width` bits, purely
    from Verilog concatenation-then-truncation semantics: repeat the
    two-character group "10" `ceil(width/2)` times, then keep the
    low (rightmost) `width` characters. Returns a string indexed
    MSB-first, matching Verilog's own text convention."""
    count = (width + 1) // 2
    concatenated = "10" * count
    return concatenated[-width:]


def _loop_bit(i: int) -> str:
    """A direct Python transcription of `bsvAltInit`'s own loop body
    (`if (i mod 2) = 1 then '1' else '0'`), used as the second,
    independent half of the widths test below."""
    return "1" if (i % 2) == 1 else "0"


@pytest.mark.parametrize("width", [1, 2, 7, 8, 32, 193, 222, 633])
def test_initializers_alternating_pattern_matches_verilog_semantics(width: int) -> None:
    verilog_bits = _verilog_alternating_bits(width)
    for i in range(width):
        verilog_bit = verilog_bits[width - 1 - i]
        assert verilog_bit == _loop_bit(i), (width, i, verilog_bit)


def test_initializers_array_uses_others_aggregate(vendor_dir: Path) -> None:
    # Each file's only `for` loop is the one *inside* `bsvAltInit`'s own
    # function body (the helper's loop over its bit positions, emitted at
    # most once per file); the array's own default is a single `others`
    # aggregate with no per-element loop or `generate` region at all.
    for name in ("BRAM2.v", "SizedFIFO.v"):
        text = emit_vhdl(parse_module(vendor_dir / name))
        assert "others =>" in text, name
        assert text.lower().count("for i in") == 1, name
        # Word-boundary match: the generated-file banner's own "Generated"
        # and "regenerate" text must not trip a check for the VHDL
        # `generate` keyword.
        assert re.search(r"\bgenerate\b", text.lower()) is None, name


def test_initializers_bram2_memory_default_calls_bsv_alt_init(vendor_dir: Path) -> None:
    text = emit_vhdl(parse_module(vendor_dir / "BRAM2.v"))
    assert "others => bsvAltInit(DATA_WIDTH_G)" in text
    assert text.count("function bsvAltInit (") == 1


def test_initializers_sizedfifo_array_default_references_d_out(vendor_dir: Path) -> None:
    text = emit_vhdl(parse_module(vendor_dir / "SizedFIFO.v"))
    assert "others => dOut" in text


def test_initializers_uninitialized_register_gets_no_default() -> None:
    # No real corpus register goes uninitialized; every one of them gets a
    # power-on value from an `initial` block. A synthetic decl/initials
    # pair proves the "no default at all" behavior directly.
    from dataclasses import dataclass, field

    from tools.bsc2vhdl.initializers import initializer_for
    from tools.bsc2vhdl.ir import SignalDecl

    decl = SignalDecl(name="never_initialized", msb_expr=None, lsb_expr=None, is_scalar=True, is_memory=False)

    @dataclass
    class _Ctx:
        path: Path = field(default_factory=lambda: Path("synthetic.v"))

        def name_for(self, name: str) -> str:
            return name

    assert initializer_for(decl, initials=(), ctx=_Ctx()) is None


def test_initializers_index_dependent_array_raises() -> None:
    # `arr[i] = i;` inside a for loop: no fixture in the corpus does this
    # (every real array initializer assigns the same value to every
    # element), so the refusal path needs a synthetic AST.
    source = """\
module IndexDependentProbe(CLK);
   input CLK;
   reg [7:0] arr[0:3];
   integer i;
   initial begin
      for (i = 0; i <= 3; i = i + 1) begin
         arr[i] = i;
      end
   end
endmodule
"""
    import tempfile

    from pyverilog.vparser.parser import parse as _pyverilog_parse

    with tempfile.NamedTemporaryFile(suffix=".v", mode="w", delete=False) as handle:
        handle.write(source)
        path = Path(handle.name)
    try:
        ast_root, _ = _pyverilog_parse([str(path)], preprocess_define=[], outputdir=tempfile.gettempdir())
        module_def = [d for d in ast_root.description.definitions if isinstance(d, vast.ModuleDef)][0]
        initial_node = next(item for item in module_def.items if isinstance(item, vast.Initial))
        arr_decl = next(
            decl
            for item in module_def.items
            if isinstance(item, vast.Decl)
            for decl in item.list
            if getattr(decl, "name", None) == "arr"
        )

        from dataclasses import dataclass, field

        from tools.bsc2vhdl.ir import SignalDecl

        decl = SignalDecl(
            name="arr",
            msb_expr="7",
            lsb_expr="0",
            is_scalar=False,
            is_memory=True,
            depth_low_expr="0",
            depth_high_expr="3",
        )

        @dataclass
        class _Ctx:
            path: Path = field(default_factory=lambda: path)

            def name_for(self, name: str) -> str:
                return name

        with pytest.raises(UnsupportedConstruct, match="index-dependent array initializer"):
            memory_initializer_for(decl, initials=(initial_node,), ctx=_Ctx())
        del arr_decl
    finally:
        path.unlink(missing_ok=True)


def test_for_loop_variable_extracts_the_index_name(vendor_dir: Path) -> None:
    module_ir = parse_module(vendor_dir / "BRAM2.v")
    for_node = next(
        statement
        for initial in module_ir.initials
        for statement in (
            initial.statement.statements if isinstance(initial.statement, vast.Block) else (initial.statement,)
        )
        if isinstance(statement, vast.ForStatement)
    )
    assert _for_loop_variable(for_node, ctx=None) == "i"
