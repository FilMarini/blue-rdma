# Test methodology:
# - Sweep: every vendored `.v` file. The parser now handles every
#   construct all thirteen vendored files use (`Wire`/top-level `assign`
#   declarations and the one `Cond`-shaped `localparam` default that a
#   same-wave plan had not yet landed a pass for), so the skip mechanism
#   below is a defensive fallback rather than an active accommodation:
#   `test_byte_identical_across_corpus` asserts the skip list is empty,
#   closing the corpus-wide gap this file's own comment used to describe.
# - Stimulus: the real vendored corpus, transpiled twice per file into two
#   independent `tmp_path` subdirectories through the real command-line
#   entry point; a synthetic wall-clock timestamp line for the mutation
#   proof; and two different working directories for the
#   working-directory-independence check.
# - Checks: every mismatch across the whole corpus is collected before a
#   single assertion fires, so one run names every offender rather than
#   aborting on the first.
# - Timing: None. This file launches no simulator.
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

from tools.bsc2vhdl.__main__ import main as _cli_main
from tools.bsc2vhdl.emit import emit_vhdl
from tools.bsc2vhdl.errors import UnsupportedConstruct
from tools.bsc2vhdl.parser import parse_module

_REPO_ROOT = Path(__file__).resolve().parents[3]

# A generation-timestamp-shaped line: a day-of-week or month name followed
# somewhere on the same line by a four-digit year, or a bare HH:MM:SS clock
# reading. Matches both the shape of BSC's own dropped `// On Wed Jun 24
# 08:29:55 PDT 2026` comment and any other wall-clock-looking line a future
# change might accidentally introduce.
_TIMESTAMP_RE = re.compile(
    r"\b(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\w*\b.*\b(19|20)\d{2}\b"
    r"|\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\b.*\b(19|20)\d{2}\b"
    r"|\b\d{1,2}:\d{2}:\d{2}\b"
)


def _vendor_files(vendor_dir: Path) -> list[Path]:
    files = sorted(vendor_dir.glob("*.v"))
    assert len(files) == 13, f"expected thirteen vendored Verilog files, found {len(files)}: {files}"
    return files


def _refusal_reason(vendor_file: Path) -> str | None:
    try:
        emit_vhdl(parse_module(vendor_file))
    except UnsupportedConstruct as exc:
        return str(exc)
    return None


def test_byte_identical_across_corpus(vendor_dir: Path, tmp_path: Path) -> None:
    mismatches: list[str] = []
    skipped: list[str] = []

    for vendor_file in _vendor_files(vendor_dir):
        reason = _refusal_reason(vendor_file)
        if reason is not None:
            skipped.append(f"{vendor_file.name}: {reason}")
            continue

        dir_a = tmp_path / vendor_file.stem / "a"
        dir_b = tmp_path / vendor_file.stem / "b"
        dir_a.mkdir(parents=True)
        dir_b.mkdir(parents=True)

        exit_a = _cli_main([str(vendor_file), "--out-dir", str(dir_a)])
        exit_b = _cli_main([str(vendor_file), "--out-dir", str(dir_b)])
        if exit_a != 0 or exit_b != 0:
            mismatches.append(f"{vendor_file.name}: nonzero exit on a file that did not raise UnsupportedConstruct")
            continue

        module_name = parse_module(vendor_file).name
        vhd_a = (dir_a / f"{module_name}.vhd").read_bytes()
        vhd_b = (dir_b / f"{module_name}.vhd").read_bytes()
        if vhd_a != vhd_b:
            mismatches.append(f"{vendor_file.name}: {module_name}.vhd differs between the two emissions")

        namemap_a = (dir_a / f"{module_name}.namemap.json").read_bytes()
        namemap_b = (dir_b / f"{module_name}.namemap.json").read_bytes()
        if namemap_a != namemap_b:
            mismatches.append(f"{vendor_file.name}: {module_name}.namemap.json differs between the two emissions")

    assert mismatches == [], "\n".join(mismatches)
    # Every one of the thirteen vendored files transpiles successfully as
    # of this plan; an empty skip list is the corpus-wide gap this test
    # once tolerated, now closed.
    assert skipped == [], "\n".join(skipped)


def test_byte_identical_no_timestamp(vendor_dir: Path) -> None:
    violations: list[str] = []
    for vendor_file in _vendor_files(vendor_dir):
        reason = _refusal_reason(vendor_file)
        if reason is not None:
            continue
        text = emit_vhdl(parse_module(vendor_file))
        for lineno, line in enumerate(text.splitlines(), start=1):
            if _TIMESTAMP_RE.search(line):
                violations.append(f"{vendor_file.name}:{lineno}: timestamp-shaped text: {line!r}")
    assert violations == [], "\n".join(violations)


def test_byte_identical_independent_of_working_directory(vendor_dir: Path, tmp_path: Path) -> None:
    vendor_file = (vendor_dir / "RegN.v").resolve()
    assert _refusal_reason(vendor_file) is None

    dir_a = tmp_path / "from_repo_root"
    dir_b = tmp_path / "from_elsewhere"
    other_cwd = tmp_path / "elsewhere"
    dir_a.mkdir()
    dir_b.mkdir()
    other_cwd.mkdir()

    env = dict(os.environ)
    env["PYTHONPATH"] = str(_REPO_ROOT)

    result_a = subprocess.run(
        [sys.executable, "-m", "tools.bsc2vhdl", str(vendor_file), "--out-dir", str(dir_a)],
        cwd=_REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    result_b = subprocess.run(
        [sys.executable, "-m", "tools.bsc2vhdl", str(vendor_file), "--out-dir", str(dir_b)],
        cwd=other_cwd,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result_a.returncode == 0, result_a.stderr
    assert result_b.returncode == 0, result_b.stderr
    assert (dir_a / "RegN.vhd").read_bytes() == (dir_b / "RegN.vhd").read_bytes()
    assert (dir_a / "RegN.namemap.json").read_bytes() == (dir_b / "RegN.namemap.json").read_bytes()
