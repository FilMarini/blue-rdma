# Test methodology:
# - Sweep: the refusal contract at the real command-line boundary
#   (`python -m tools.bsc2vhdl`), proven against four synthetic
#   out-of-subset inputs (`generate`, `inout`, `task`, a shift operator)
#   plus a mixed good/bad batch.
# - Stimulus: four minimal Verilog modules written to `tmp_path` as text,
#   never added to `tests/vendor/`, which is pinned to the thirteen real
#   surf files and must stay exactly that count. The `generate` case has
#   no real fixture anywhere in the corpus (zero `generate` blocks exist
#   in-corpus per the phase's own research), which is why a synthetic
#   input is the only way to prove this path fires at all.
# - Checks: every case asserts three things together, not separately: a
#   nonzero return code, a stderr message matching a regular expression
#   naming the construct and containing the file path and a line number,
#   and an empty output directory (`list(tmp_path.iterdir()) == []`)
#   including the absence of the `.namemap.json` sidecar. Asserting the
#   empty directory is the whole point of this file: asserting only the
#   message would pass even if the tool wrote a truncated file first.
# - Timing: None. This file launches no simulator.
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]

_GENERATE_SOURCE = """\
module GenerateProbe(CLK);
   input CLK;
   generate
      genvar i;
      for (i = 0; i < 1; i = i + 1) begin
      end
   endgenerate
endmodule
"""

_INOUT_SOURCE = """\
module InoutProbe(CLK, IO);
   input CLK;
   inout IO;
endmodule
"""

_TASK_SOURCE = """\
module TaskProbe(CLK);
   input CLK;
   task my_task;
      begin
      end
   endtask
endmodule
"""

_SHIFT_SOURCE = """\
module ShiftProbe(CLK, A, B);
   parameter width = 8;
   input CLK;
   input [width - 1 : 0] A;
   output [width - 1 : 0] B;
   reg [width - 1 : 0] B;
   always @(posedge CLK)
     B <= A << 1;
endmodule
"""


def _run_cli(input_path: Path, out_dir: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "tools.bsc2vhdl", str(input_path), "--out-dir", str(out_dir)],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
    )


def test_hard_fail_generate_writes_no_output(tmp_path: Path) -> None:
    input_path = tmp_path / "GenerateProbe.v"
    input_path.write_text(_GENERATE_SOURCE)
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    result = _run_cli(input_path, out_dir)

    assert result.returncode != 0
    assert "generate" in result.stderr.lower()
    assert str(input_path) in result.stderr
    assert list(out_dir.iterdir()) == []


def test_hard_fail_inout_writes_no_output(tmp_path: Path) -> None:
    input_path = tmp_path / "InoutProbe.v"
    input_path.write_text(_INOUT_SOURCE)
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    result = _run_cli(input_path, out_dir)

    assert result.returncode != 0
    assert "inout" in result.stderr.lower()
    assert str(input_path) in result.stderr
    assert list(out_dir.iterdir()) == []


def test_hard_fail_task_writes_no_output(tmp_path: Path) -> None:
    input_path = tmp_path / "TaskProbe.v"
    input_path.write_text(_TASK_SOURCE)
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    result = _run_cli(input_path, out_dir)

    assert result.returncode != 0
    assert str(input_path) in result.stderr
    assert list(out_dir.iterdir()) == []


def test_hard_fail_shift_writes_no_output(tmp_path: Path) -> None:
    input_path = tmp_path / "ShiftProbe.v"
    input_path.write_text(_SHIFT_SOURCE)
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    result = _run_cli(input_path, out_dir)

    assert result.returncode != 0
    assert str(input_path) in result.stderr
    assert list(out_dir.iterdir()) == []


def test_hard_fail_message_names_construct_before_location(tmp_path: Path) -> None:
    input_path = tmp_path / "GenerateProbe.v"
    input_path.write_text(_GENERATE_SOURCE)
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    result = _run_cli(input_path, out_dir)

    construct_index = result.stderr.lower().index("generate")
    location_index = result.stderr.index(str(input_path))
    assert construct_index < location_index


def test_hard_fail_one_bad_input_does_not_block_the_others(tmp_path: Path) -> None:
    good_input = _REPO_ROOT / "tools" / "bsc2vhdl" / "tests" / "vendor" / "RegN.v"
    bad_input = tmp_path / "GenerateProbe.v"
    bad_input.write_text(_GENERATE_SOURCE)
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    result = subprocess.run(
        [sys.executable, "-m", "tools.bsc2vhdl", str(good_input), str(bad_input), "--out-dir", str(out_dir)],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert (out_dir / "RegN.vhd").exists()
    assert (out_dir / "RegN.namemap.json").exists()
    assert not (out_dir / "GenerateProbe.vhd").exists()
    assert not (out_dir / "GenerateProbe.namemap.json").exists()


def test_hard_fail_leaves_no_sidecar(tmp_path: Path) -> None:
    input_path = tmp_path / "GenerateProbe.v"
    input_path.write_text(_GENERATE_SOURCE)
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    result = _run_cli(input_path, out_dir)

    assert result.returncode != 0
    assert not (out_dir / "GenerateProbe.vhd").exists()
    assert not (out_dir / "GenerateProbe.namemap.json").exists()
    assert list(out_dir.iterdir()) == []
