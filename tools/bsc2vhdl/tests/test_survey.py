# Test methodology:
# - Sweep: the collect-all-refusals contract at both the function boundary
#   (`survey_module`) and the real command-line boundary
#   (`python -m tools.bsc2vhdl --survey`), proven against a synthetic input
#   holding two independent out-of-subset constructs at two different
#   lines, so a single-refusal fixture cannot hide a walk that still stops
#   at the first offender.
# - Stimulus: one minimal Verilog module written to `tmp_path` as text
#   (never added to `tests/vendor/`, which is pinned to the thirteen real
#   surf files), plus the vendored `RegN.v` fixture to prove a clean input
#   surveys to zero refusals.
# - Checks: `survey_module` returns a list of the right length; the CLI
#   prints both refusal messages, the per-file summary line, and the total
#   line; a `--survey` run leaves its target directory with no `.vhd` and
#   no `.namemap.json` and never creates one that did not already exist;
#   the same input without `--survey` exits 1 while `--survey` exits 0;
#   and `--survey` combined with `--manifest` is rejected naming both
#   flags.
# - Timing: None. This file launches no simulator.
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from tools.bsc2vhdl.parser import survey_module

_REPO_ROOT = Path(__file__).resolve().parents[3]

_TWO_REFUSAL_SOURCE = """\
module TwoRefusalProbe(CLK, RST_N, A);
   input CLK;
   input RST_N;
   input A;
   generate
      genvar i;
      for (i = 0; i < 1; i = i + 1) begin
      end
   endgenerate
   task my_task;
      begin
      end
   endtask
endmodule
"""


def _run_cli(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "tools.bsc2vhdl", *args],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
    )


def test_survey_module_continues_past_first_refusal(tmp_path: Path) -> None:
    input_path = tmp_path / "TwoRefusalProbe.v"
    input_path.write_text(_TWO_REFUSAL_SOURCE)

    refusals = survey_module(input_path)

    assert len(refusals) == 2
    assert "generate" in str(refusals[0]).lower()
    assert "task" in str(refusals[1]).lower()


def test_survey_module_clean_input_reports_zero(vendor_dir: Path) -> None:
    refusals = survey_module(vendor_dir / "RegN.v")

    assert refusals == []


def test_survey_cli_prints_both_refusals_and_summary_lines(tmp_path: Path) -> None:
    input_path = tmp_path / "TwoRefusalProbe.v"
    input_path.write_text(_TWO_REFUSAL_SOURCE)

    result = _run_cli([str(input_path), "--survey"])

    assert result.returncode == 0
    assert "generate" in result.stdout.lower()
    assert "task" in result.stdout.lower()
    assert f"survey: 2 refusal(s) in {input_path}" in result.stdout
    assert "survey total: 2 refusal(s) across 1 file(s)" in result.stdout


def test_survey_cli_writes_nothing(tmp_path: Path) -> None:
    input_path = tmp_path / "TwoRefusalProbe.v"
    input_path.write_text(_TWO_REFUSAL_SOURCE)

    result = _run_cli([str(input_path), "--survey"])

    assert result.returncode == 0
    assert list(tmp_path.iterdir()) == [input_path]
    assert not (tmp_path / "TwoRefusalProbe.vhd").exists()
    assert not (tmp_path / "TwoRefusalProbe.namemap.json").exists()


def test_survey_cli_exits_zero_while_non_survey_exits_one(tmp_path: Path) -> None:
    input_path = tmp_path / "TwoRefusalProbe.v"
    input_path.write_text(_TWO_REFUSAL_SOURCE)
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    survey_result = _run_cli([str(input_path), "--survey"])
    emit_result = _run_cli([str(input_path), "--out-dir", str(out_dir)])

    assert survey_result.returncode == 0
    assert emit_result.returncode == 1


def test_survey_rejects_manifest_naming_both_flags(tmp_path: Path) -> None:
    input_path = tmp_path / "TwoRefusalProbe.v"
    input_path.write_text(_TWO_REFUSAL_SOURCE)
    manifest_path = tmp_path / "manifest.json"

    result = _run_cli([str(input_path), "--survey", "--manifest", str(manifest_path)])

    assert result.returncode != 0
    assert "--survey" in result.stderr
    assert "--manifest" in result.stderr
    assert not manifest_path.exists()


def test_emit_without_out_dir_fails_loudly(tmp_path: Path) -> None:
    input_path = tmp_path / "TwoRefusalProbe.v"
    input_path.write_text(_TWO_REFUSAL_SOURCE)

    result = _run_cli([str(input_path)])

    assert result.returncode != 0
    assert "--out-dir" in result.stderr
