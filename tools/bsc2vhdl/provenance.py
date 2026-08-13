"""Provenance manifest for transpiled fixtures.

A tool-produced JSON record, one entry per emitted file, of the source
Verilog's digest, the transpiler version that produced the output, and the
emitted VHDL's own digest. The digests are integrity checks against
accidental drift, not a security property: the same posture
`tests/common/equivalence_engine.py`'s `assert_sidecar_current` already
takes for a stale golden in the surf tree.

`build_manifest` is the one place the manifest's JSON shape and formatting
are defined, so a re-run at a fixed tool version reproduces byte-identical
output: entries are sorted by source file name regardless of the order the
caller built them in, with two-space indentation and a trailing newline.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from . import __version__


@dataclass(frozen=True)
class ManifestEntry:
    """One emitted file's provenance record.

    `source_path` is the source file's own name only, never the full path
    a caller gave on the command line, so the manifest is identical
    regardless of which absolute or relative path the tool was invoked
    with.
    """

    source_path: str
    source_sha256: str
    output_file: str
    output_sha256: str


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def manifest_entry(source_path: Path, output_file: str, output_text: str) -> ManifestEntry:
    """Build one entry from a source file already on disk and the text
    already emitted for it. `output_text` is hashed as UTF-8, matching how
    it is written to disk.
    """
    return ManifestEntry(
        source_path=source_path.name,
        source_sha256=sha256_file(source_path),
        output_file=output_file,
        output_sha256=sha256_bytes(output_text.encode("utf-8")),
    )


def _entry_payload(entry: ManifestEntry) -> dict:
    return {
        "source_path": entry.source_path,
        "source_sha256": entry.source_sha256,
        "output_file": entry.output_file,
        "output_sha256": entry.output_sha256,
        "transpiler_version": __version__,
    }


def _serialize(entries_by_name: dict) -> str:
    payload = {"entries": dict(sorted(entries_by_name.items()))}
    return json.dumps(payload, indent=2) + "\n"


def build_manifest(entries: Iterable[ManifestEntry]) -> str:
    """Serialize `entries` into the manifest's deterministic JSON text."""
    by_name = {entry.source_path: _entry_payload(entry) for entry in entries}
    return _serialize(by_name)


def merge_manifest(existing_entries: dict, entries: Iterable[ManifestEntry]) -> str:
    """Merge `entries` into `existing_entries` and serialize the result
    through the same deterministic, sorted-by-name JSON text `build_manifest`
    produces.

    `existing_entries` is the raw `"entries"` mapping of a previously
    written manifest (or an empty dict if no manifest exists yet), spanning
    however many prior invocations wrote it. This invocation's own entries
    replace or add exactly the keys they name; every other key in
    `existing_entries` passes through verbatim, including whatever
    `transpiler_version` it was recorded with, so a manifest spanning two
    output directories can be produced by two invocations without either one
    losing the other's entries. This is the one place the merge itself
    happens, next to `build_manifest`, so `__main__.py` only decides whether
    to pass in a prior mapping.
    """
    merged = dict(existing_entries)
    for entry in entries:
        merged[entry.source_path] = _entry_payload(entry)
    return _serialize(merged)
