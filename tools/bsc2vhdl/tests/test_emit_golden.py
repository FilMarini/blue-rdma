# Test methodology:
# - Sweep: The whole emitted `RegN.vhd` text, compared byte for byte
#   against a committed golden, plus a second independent emission
#   compared against the first.
# - Stimulus: The vendored `RegN.v` fixture, emitted twice into two
#   separate `tmp_path` directories.
# - Checks: Byte-for-byte comparison against the committed golden;
#   byte-for-byte comparison between the two independent emissions;
#   a scan for any non-ASCII byte, any tab, and any trailing whitespace.
# - Timing: None. This file launches no simulator.
from __future__ import annotations

import re
from pathlib import Path

from tools.bsc2vhdl.emit import emit_vhdl
from tools.bsc2vhdl.parser import parse_module

_GOLDEN_DIR = Path(__file__).resolve().parent / "golden"
_FORBIDDEN_RE = re.compile(r"[^\x00-\x7F]|\t| +$", re.MULTILINE)


def test_emit_vhdl_matches_golden(vendor_dir: Path) -> None:
    module_ir = parse_module(vendor_dir / "RegN.v")
    text = emit_vhdl(module_ir)
    golden = (_GOLDEN_DIR / "RegN.vhd").read_text()
    assert text == golden


def test_emit_vhdl_is_byte_identical_on_rerun(vendor_dir: Path) -> None:
    first = emit_vhdl(parse_module(vendor_dir / "RegN.v"))
    second = emit_vhdl(parse_module(vendor_dir / "RegN.v"))
    assert first == second


def test_emit_vhdl_has_no_forbidden_bytes(vendor_dir: Path) -> None:
    text = emit_vhdl(parse_module(vendor_dir / "RegN.v"))
    assert _FORBIDDEN_RE.search(text) is None
