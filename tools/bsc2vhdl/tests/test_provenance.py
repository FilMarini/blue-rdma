# Test methodology:
# - Sweep: the thirteen vendored `.v` files only, matched against the
#   fork's own committed manifest at `tests/golden/manifest.json`. Neither
#   drift test in this file reads anything under a surf checkout; that half
#   of drift detection is `tests/ethernet/RoCEv2/test_TranspiledProvenance.py`
#   in the surf submodule, which needs no transpiler in return. The
#   `--manifest-merge` tests below build their own scratch manifests in
#   `tmp_path` and are independent of the committed golden manifest.
# - Stimulus: `test_provenance_output_hashes` regenerates all thirteen
#   vendored files into `tmp_path` through the real command-line entry
#   point; `test_provenance_source_hashes` reads the vendored copies
#   directly, no regeneration needed. The merge tests drive
#   `python -m tools.bsc2vhdl` directly (via `_cli_main`) over small,
#   disjoint subsets of the vendored corpus so each invocation's own effect
#   on a scratch manifest is unambiguous.
# - Checks: every recorded output digest still matches a fresh regeneration,
#   and every recorded source digest still matches the vendored copy on
#   disk, each collecting every mismatch before asserting once. The merge
#   tests check byte-identical preservation of untouched entries, byte-
#   identical re-merge of an unchanged input, the partial-run refusal
#   holding in merge mode, and the two `--manifest-merge` rejection cases
#   (`--manifest-merge` without `--manifest`; `--manifest-merge` with
#   `--survey`).
# - Timing: None. This file launches no simulator.
#
# Regenerate this manifest with:
#   python -m tools.bsc2vhdl tools/bsc2vhdl/tests/vendor/*.v \
#       --out-dir /tmp/bsc2vhdl-manifest-regen \
#       --manifest tools/bsc2vhdl/tests/golden/manifest.json
# then discard /tmp/bsc2vhdl-manifest-regen; only the manifest itself is
# committed here, alongside the thirteen already-committed vendored `.v`
# files the manifest's own source hashes describe.
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.bsc2vhdl.__main__ import main as _cli_main
from tools.bsc2vhdl.provenance import sha256_file

_MANIFEST_PATH = Path(__file__).resolve().parent / "golden" / "manifest.json"


def _load_manifest() -> dict:
    payload = json.loads(_MANIFEST_PATH.read_text())
    entries = payload["entries"]
    assert len(entries) == 13, f"expected thirteen manifest entries, found {len(entries)}"
    return entries


def test_provenance_source_hashes(vendor_dir: Path) -> None:
    manifest = _load_manifest()
    mismatches: list[str] = []
    for source_name, entry in manifest.items():
        vendor_file = vendor_dir / source_name
        if not vendor_file.is_file():
            mismatches.append(f"{source_name}: not found under {vendor_dir}")
            continue
        actual = sha256_file(vendor_file)
        if actual != entry["source_sha256"]:
            mismatches.append(
                f"{source_name}: manifest records {entry['source_sha256']}, vendored copy is now {actual}"
            )
    assert mismatches == [], "\n".join(mismatches)


def test_provenance_output_hashes(vendor_dir: Path, tmp_path: Path) -> None:
    manifest = _load_manifest()
    vendor_files = sorted(vendor_dir.glob("*.v"))
    assert len(vendor_files) == 13, f"expected thirteen vendored files, found {len(vendor_files)}"

    exit_code = _cli_main([str(f) for f in vendor_files] + ["--out-dir", str(tmp_path)])
    assert exit_code == 0, "regeneration of the vendored corpus failed"

    mismatches: list[str] = []
    for source_name, entry in manifest.items():
        output_path = tmp_path / entry["output_file"]
        if not output_path.is_file():
            mismatches.append(f"{source_name}: {entry['output_file']} was not regenerated")
            continue
        actual = sha256_file(output_path)
        if actual != entry["output_sha256"]:
            mismatches.append(
                f"{source_name}: manifest records {entry['output_sha256']}, regeneration produced {actual}"
            )
    assert mismatches == [], "\n".join(mismatches)


def test_provenance_manifest_merge_preserves_unrelated_entries(vendor_dir: Path, tmp_path: Path) -> None:
    """A merge into an existing manifest replaces or adds only the keys its
    own inputs produced; every other entry survives byte-identically."""
    out_dir = tmp_path / "out"
    manifest_path = tmp_path / "PROVENANCE.json"

    base_inputs = [vendor_dir / "RegN.v", vendor_dir / "RegUN.v"]
    exit_code = _cli_main(
        [str(f) for f in base_inputs] + ["--out-dir", str(out_dir), "--manifest", str(manifest_path)]
    )
    assert exit_code == 0
    base_entries = json.loads(manifest_path.read_text())["entries"]

    exit_code = _cli_main(
        [
            str(vendor_dir / "Counter.v"),
            "--out-dir",
            str(out_dir),
            "--manifest",
            str(manifest_path),
            "--manifest-merge",
        ]
    )
    assert exit_code == 0
    merged_entries = json.loads(manifest_path.read_text())["entries"]

    assert set(merged_entries) == {"RegN.v", "RegUN.v", "Counter.v"}
    assert merged_entries["RegN.v"] == base_entries["RegN.v"]
    assert merged_entries["RegUN.v"] == base_entries["RegUN.v"]


def test_provenance_manifest_remerge_unchanged_input_is_byte_identical(vendor_dir: Path, tmp_path: Path) -> None:
    """Re-merging an input whose source and output have not changed
    reproduces the exact same manifest bytes, not merely the same entries,
    since a re-run at a fixed tool version must be indistinguishable from
    not having run at all."""
    out_dir = tmp_path / "out"
    manifest_path = tmp_path / "PROVENANCE.json"

    exit_code = _cli_main([str(vendor_dir / "RegN.v"), "--out-dir", str(out_dir), "--manifest", str(manifest_path)])
    assert exit_code == 0
    once = manifest_path.read_text()

    exit_code = _cli_main(
        [
            str(vendor_dir / "RegN.v"),
            "--out-dir",
            str(out_dir),
            "--manifest",
            str(manifest_path),
            "--manifest-merge",
        ]
    )
    assert exit_code == 0
    twice = manifest_path.read_text()

    assert once == twice


def test_provenance_manifest_merge_failed_input_writes_nothing(vendor_dir: Path, tmp_path: Path) -> None:
    """The partial-run refusal holds in merge mode too: an invocation with
    one failed input leaves the prior manifest completely untouched rather
    than merging in whatever partial entries succeeded."""
    out_dir = tmp_path / "out"
    manifest_path = tmp_path / "PROVENANCE.json"

    exit_code = _cli_main([str(vendor_dir / "RegN.v"), "--out-dir", str(out_dir), "--manifest", str(manifest_path)])
    assert exit_code == 0
    before = manifest_path.read_text()

    bad_input = tmp_path / "GenerateProbe.v"
    bad_input.write_text(
        "module GenerateProbe(CLK);\n"
        "   input CLK;\n"
        "   generate\n"
        "      genvar i;\n"
        "      for (i = 0; i < 1; i = i + 1) begin\n"
        "      end\n"
        "   endgenerate\n"
        "endmodule\n"
    )

    exit_code = _cli_main(
        [str(bad_input), "--out-dir", str(out_dir), "--manifest", str(manifest_path), "--manifest-merge"]
    )
    assert exit_code != 0
    assert manifest_path.read_text() == before


def test_provenance_manifest_merge_without_manifest_is_rejected(vendor_dir: Path, tmp_path: Path) -> None:
    """--manifest-merge with no --manifest names nothing to merge into and
    is rejected at argument-parsing time, before any input is processed."""
    out_dir = tmp_path / "out"
    with pytest.raises(SystemExit):
        _cli_main([str(vendor_dir / "RegN.v"), "--out-dir", str(out_dir), "--manifest-merge"])


def test_provenance_manifest_merge_with_survey_is_rejected(vendor_dir: Path) -> None:
    """A census produces no entries to merge, so --manifest-merge combined
    with --survey is rejected the same way --manifest combined with
    --survey already is."""
    with pytest.raises(SystemExit):
        _cli_main([str(vendor_dir / "RegN.v"), "--survey", "--manifest-merge"])
