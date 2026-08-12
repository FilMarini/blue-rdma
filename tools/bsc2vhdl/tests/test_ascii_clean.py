# Test methodology:
# - Sweep: every vendored `.v` file that transpiles successfully today (a
#   file still refused by a construct a same-wave plan has not yet landed
#   a pass for is excluded from these checks rather than failed, matching
#   `test_byte_identical.py`'s posture at this point in the wave).
# - Stimulus: the real vendored corpus, transpiled once per file.
# - Checks: every violation across the whole corpus is collected before a
#   single assertion fires, so one run names every offending file and
#   line rather than aborting on the first. surf CI rejects a tab, a
#   non-ASCII byte, or trailing whitespace in any `.vhd` with no exclusion
#   mechanism at all, so a carried-through tab from the Verilog source's
#   own instantiation-continuation-line tabs is an unfixable CI failure
#   rather than a lint warning.
# - Timing: None. This file launches no simulator.
from __future__ import annotations

from pathlib import Path

from tools.bsc2vhdl.emit import emit_vhdl
from tools.bsc2vhdl.errors import UnsupportedConstruct
from tools.bsc2vhdl.parser import parse_module


def _vendor_files(vendor_dir: Path) -> list[Path]:
    files = sorted(vendor_dir.glob("*.v"))
    assert len(files) == 13, f"expected thirteen vendored Verilog files, found {len(files)}: {files}"
    return files


def _emitted_texts(vendor_dir: Path) -> dict[str, str]:
    """Every vendored file's emitted text, keyed by file name, excluding
    any file that still refuses a construct a same-wave plan has not yet
    landed a pass for."""
    texts: dict[str, str] = {}
    for vendor_file in _vendor_files(vendor_dir):
        try:
            texts[vendor_file.name] = emit_vhdl(parse_module(vendor_file))
        except UnsupportedConstruct:
            continue
    return texts


def test_emitted_files_are_ascii_clean(vendor_dir: Path) -> None:
    violations: list[str] = []
    for name, text in _emitted_texts(vendor_dir).items():
        for lineno, line in enumerate(text.splitlines(), start=1):
            if any(ord(char) > 0x7F for char in line):
                violations.append(f"{name}:{lineno}: non-ASCII byte")
            if "\t" in line:
                violations.append(f"{name}:{lineno}: tab character")
            if line != line.rstrip():
                violations.append(f"{name}:{lineno}: trailing whitespace")
    assert violations == [], "\n".join(violations)


def test_emitted_files_end_with_exactly_one_newline(vendor_dir: Path) -> None:
    violations: list[str] = []
    for name, text in _emitted_texts(vendor_dir).items():
        data = text.encode()
        if not data.endswith(b"\n"):
            violations.append(f"{name}: does not end with a newline")
        elif data.endswith(b"\n\n"):
            violations.append(f"{name}: ends with more than one newline")
    assert violations == [], "\n".join(violations)
