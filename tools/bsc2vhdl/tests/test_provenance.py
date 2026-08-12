# Test methodology:
# - Sweep: the thirteen vendored `.v` files only, matched against the
#   fork's own committed manifest at `tests/golden/manifest.json`. Neither
#   test in this file reads anything under a surf checkout; that half of
#   drift detection is `tests/ethernet/RoCEv2/test_TranspiledProvenance.py`
#   in the surf submodule, which needs no transpiler in return.
# - Stimulus: `test_provenance_output_hashes` regenerates all thirteen
#   vendored files into `tmp_path` through the real command-line entry
#   point; `test_provenance_source_hashes` reads the vendored copies
#   directly, no regeneration needed.
# - Checks: every recorded output digest still matches a fresh regeneration,
#   and every recorded source digest still matches the vendored copy on
#   disk, each collecting every mismatch before asserting once.
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
