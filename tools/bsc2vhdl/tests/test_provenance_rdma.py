# Test methodology:
# - Sweep: the three vendored generated blue-rdma `.v` files only
#   (`mkQP.v`, `mkTransportLayer.v`, `mkAxisTransportLayer.v`), matched
#   against the fork's own committed manifest at
#   `tests/golden/manifest_rdma.json`. This is the RDMA-specific half of
#   `tests/test_provenance.py`, split into its own module and its own
#   manifest because these three files are two to three orders of magnitude
#   larger than any of the thirteen blue-lib primitives that manifest
#   already covers, and mixing them into one glob would silently make every
#   default test run transpile 53k extra lines.
# - Stimulus: `test_provenance_rdma_source_hashes` reads the vendored
#   copies directly, no regeneration needed, and is always on. Combined
#   with the existing `test_provenance_source_hashes` over the thirteen
#   blue-lib files, every one of the sixteen vendored sources is hashed on
#   a default run. `test_provenance_rdma_output_hashes` regenerates all
#   three vendored files through the real command-line entry point and is
#   gated by `BSC2VHDL_RDMA_REGEN`, since a from-scratch transpile of
#   `mkQP.v` alone takes measurably longer than the whole thirteen-file
#   blue-lib corpus. The regeneration copies the three vendored inputs into
#   `tmp_path` and points `--out-dir` at that same directory: `mkQP`'s
#   component declaration inside `mkTransportLayer.vhd` has twelve
#   `statusSQ_comm_get*` status outputs left entirely unconnected at its
#   own instantiation site, and `instantiate.py`'s `_load_committed_entity_
#   ports` backstop resolves their real (non-scalar) width by reading an
#   already-promoted `<module>.vhd` sitting next to the `.v` file being
#   transpiled -- so `mkQP.v` must be transpiled into the same directory
#   its own `.v` source lives in before `mkTransportLayer.v` is
#   transpiled, exactly as it is when regenerating any of these three
#   files in place inside a real surf checkout.
# - Checks: every recorded output digest still matches a fresh
#   regeneration, and every recorded source digest still matches the
#   vendored copy on disk, each collecting every mismatch before asserting
#   once, matching `tests/test_provenance.py`'s own style.
# - Timing: None for the source-hash test. The output-hash test transpiles
#   roughly 53k lines of generated Verilog, which is why it is gated
#   behind `BSC2VHDL_RDMA_REGEN` rather than run by default.
#
# Regenerate this manifest with:
#   mkdir -p /tmp/bsc2vhdl-rdma-manifest-regen
#   cp tools/bsc2vhdl/tests/vendor_rdma/*.v /tmp/bsc2vhdl-rdma-manifest-regen/
#   python -m tools.bsc2vhdl /tmp/bsc2vhdl-rdma-manifest-regen/*.v \
#       --out-dir /tmp/bsc2vhdl-rdma-manifest-regen \
#       --manifest tools/bsc2vhdl/tests/golden/manifest_rdma.json
# then discard /tmp/bsc2vhdl-rdma-manifest-regen; only the manifest itself
# is committed here, alongside the three already-committed vendored `.v`
# files the manifest's own source hashes describe. Copying the inputs into
# a scratch directory and pointing --out-dir at that same directory (rather
# than transpiling tests/vendor_rdma/*.v directly with --out-dir elsewhere)
# is required, not cosmetic: it is what makes mkQP.vhd available as a
# sibling of mkTransportLayer.v by the time the latter transpiles.
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest

from tools.bsc2vhdl.__main__ import main as _cli_main
from tools.bsc2vhdl.provenance import sha256_file

_MANIFEST_PATH = Path(__file__).resolve().parent / "golden" / "manifest_rdma.json"


def _load_manifest() -> dict:
    payload = json.loads(_MANIFEST_PATH.read_text())
    entries = payload["entries"]
    assert len(entries) == 3, f"expected three manifest entries, found {len(entries)}"
    return entries


def test_provenance_rdma_source_hashes(vendor_rdma_dir: Path) -> None:
    manifest = _load_manifest()
    mismatches: list[str] = []
    for source_name, entry in manifest.items():
        vendor_file = vendor_rdma_dir / source_name
        if not vendor_file.is_file():
            mismatches.append(f"{source_name}: not found under {vendor_rdma_dir}")
            continue
        actual = sha256_file(vendor_file)
        if actual != entry["source_sha256"]:
            mismatches.append(
                f"{source_name}: manifest records {entry['source_sha256']}, vendored copy is now {actual}"
            )
    assert mismatches == [], "\n".join(mismatches)


@pytest.mark.skipif(
    "BSC2VHDL_RDMA_REGEN" not in os.environ,
    reason="set BSC2VHDL_RDMA_REGEN=1 to run byte-identical regeneration of the three vendored RDMA "
    "modules; this transpiles roughly 53k lines and is skipped by default",
)
def test_provenance_rdma_output_hashes(vendor_rdma_dir: Path, tmp_path: Path) -> None:
    manifest = _load_manifest()
    vendor_files = sorted(vendor_rdma_dir.glob("*.v"))
    assert len(vendor_files) == 3, f"expected three vendored files, found {len(vendor_files)}"

    staged_files = []
    for vendor_file in vendor_files:
        staged_file = tmp_path / vendor_file.name
        shutil.copyfile(vendor_file, staged_file)
        staged_files.append(staged_file)

    exit_code = _cli_main([str(f) for f in staged_files] + ["--out-dir", str(tmp_path)])
    assert exit_code == 0, "regeneration of the vendored RDMA corpus failed"

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
