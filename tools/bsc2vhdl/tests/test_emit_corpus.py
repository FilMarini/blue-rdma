# Test methodology:
# - Sweep: all thirteen vendored blue-lib `.v` files, discovered by glob and
#   pinned at exactly thirteen, run through the real `python -m
#   tools.bsc2vhdl` command-line entry point.
# - Stimulus: the real vendored corpus. `test_emit_corpus_all_thirteen_emit`
#   needs no other repository at all; `test_emit_corpus_all_thirteen_analyze`
#   and `test_emit_corpus_all_thirteen_vsg_clean` additionally need a surf
#   checkout with a pre-analyzed `build/surf-obj08.cf` work library and a
#   `vsg-linter.yml`, located from the `BSC2VHDL_SURF_ROOT` environment
#   variable (documented default: the sibling surf checkout used in this
#   workspace). Either test skips, with an explicit reason, when that
#   checkout or its build library is absent, so the blue-rdma suite stays
#   runnable on a machine with no surf tree at all -- this is the one place
#   the two repositories touch, and it is a skip, never a hard dependency,
#   because the tool itself must not require surf (D-06).
# - Checks: every failure across every file is collected before a single
#   assertion fires, so one run names every offender instead of stopping at
#   the first.
# - Timing: none for the emit test. `test_emit_corpus_all_thirteen_analyze`
#   and `test_emit_corpus_all_thirteen_vsg_clean` each launch one `ghdl`/`vsg`
#   subprocess per file; neither drives a clock or any stimulus.
from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]

_DEFAULT_SURF_ROOT = (
    "/sdf/group/faders/users/ruckman/project/SimpleExamples/"
    "Simple-10GbE-RUDP-KCU105-Example/firmware/submodules/surf"
)

_BASE_GHDL_COMPILE_ARGS = ["--std=08", "-fsynopsys", "-frelaxed-rules", "-fexplicit"]
_WORK_LIBRARY = "surf"


def _surf_root() -> Path:
    return Path(os.environ.get("BSC2VHDL_SURF_ROOT", _DEFAULT_SURF_ROOT))


def _surf_build_dir() -> Path:
    return _surf_root() / "build"


def _vendor_files(vendor_dir: Path) -> list[Path]:
    files = sorted(vendor_dir.glob("*.v"))
    assert len(files) == 13, f"expected thirteen vendored Verilog files, found {len(files)}: {files}"
    return files


def _ghdl_command() -> list[str]:
    return shlex.split(os.environ.get("GHDL_CMD", "ghdl"))


def _vsg_command() -> list[str]:
    return shlex.split(os.environ.get("VSG_CMD", "vsg"))


def test_emit_corpus_all_thirteen_emit(vendor_dir: Path, tmp_path: Path) -> None:
    inputs = _vendor_files(vendor_dir)
    result = subprocess.run(
        [sys.executable, "-m", "tools.bsc2vhdl", *[str(path) for path in inputs], "--out-dir", str(tmp_path)],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert len(sorted(tmp_path.glob("*.vhd"))) == 13
    assert len(sorted(tmp_path.glob("*.namemap.json"))) == 13


def test_emit_corpus_all_thirteen_analyze(vendor_dir: Path, tmp_path: Path) -> None:
    build_lib = _surf_build_dir() / "surf-obj08.cf"
    if not build_lib.is_file():
        import pytest

        pytest.skip(f"no pre-analyzed surf work library at {build_lib}; set BSC2VHDL_SURF_ROOT to a surf checkout")

    inputs = _vendor_files(vendor_dir)
    exit_code = subprocess.run(
        [sys.executable, "-m", "tools.bsc2vhdl", *[str(path) for path in inputs], "--out-dir", str(tmp_path)],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
    ).returncode
    assert exit_code == 0

    common_args = [
        *_BASE_GHDL_COMPILE_ARGS,
        f"--work={_WORK_LIBRARY}",
        f"-P{_surf_build_dir()}",
        f"--workdir={_surf_build_dir()}",
    ]

    failures: list[str] = []
    for vhdl_file in sorted(tmp_path.glob("*.vhd")):
        result = subprocess.run(
            [*_ghdl_command(), "-a", *common_args, str(vhdl_file)],
            cwd=_surf_root(),
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            failures.append(f"{vhdl_file.name}: analyze failed (exit {result.returncode})\n{result.stderr}")

    assert failures == [], "\n\n".join(failures)


def test_emit_corpus_all_thirteen_vsg_clean(vendor_dir: Path, tmp_path: Path) -> None:
    linter_config = _surf_root() / "vsg-linter.yml"
    if not linter_config.is_file():
        import pytest

        pytest.skip(f"no vsg-linter.yml at {linter_config}; set BSC2VHDL_SURF_ROOT to a surf checkout")

    inputs = _vendor_files(vendor_dir)
    exit_code = subprocess.run(
        [sys.executable, "-m", "tools.bsc2vhdl", *[str(path) for path in inputs], "--out-dir", str(tmp_path)],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
    ).returncode
    assert exit_code == 0

    failures: list[str] = []
    for vhdl_file in sorted(tmp_path.glob("*.vhd")):
        result = subprocess.run(
            [*_vsg_command(), "-c", str(linter_config), "-f", str(vhdl_file)],
            cwd=_surf_root(),
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            failures.append(f"{vhdl_file.name}: vsg reported violations (exit {result.returncode})\n{result.stdout}")

    assert failures == [], "\n\n".join(failures)
