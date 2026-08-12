"""Command-line entry point: `python -m tools.bsc2vhdl <inputs...> --out-dir DIR`.

Takes explicit input files and an explicit `--out-dir` and writes nowhere
else: no surf path and no default output directory are baked in. For each
input, the whole VHDL text and the whole name-map JSON are built in memory
first; only when both are complete are they written to a temporary file in
the target directory and moved into place with `os.replace`. A refused
construct prints its message to stderr, writes nothing for that input, and
the process continues to the remaining inputs before exiting nonzero.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

from . import __version__
from . import instantiate as _instantiate
from .emit import emit_vhdl
from .errors import UnsupportedConstruct
from .mangle import NameMap
from .parser import parse_module
from .provenance import ManifestEntry, build_manifest, manifest_entry


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m tools.bsc2vhdl")
    parser.add_argument("inputs", nargs="+", help="one or more BSC-generated .v files")
    parser.add_argument("--out-dir", required=True, help="directory to write .vhd and .namemap.json output into")
    parser.add_argument("--manifest", default=None, help="path to write a provenance manifest JSON")
    parser.add_argument("--version", action="version", version=f"bsc2vhdl {__version__}")
    return parser


def _resolve_output_path(out_dir: Path, name: str) -> Path:
    candidate = (out_dir / name).resolve()
    if out_dir not in candidate.parents and candidate != out_dir:
        raise ValueError(f"refusing to write outside --out-dir: {candidate}")
    return candidate


def _atomic_write(path: Path, text: str) -> None:
    directory = path.parent
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=directory)
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(text)
        os.replace(tmp_name, path)
    except BaseException:
        if os.path.exists(tmp_name):
            os.remove(tmp_name)
        raise


def _process_one(input_path: Path, out_dir: Path) -> ManifestEntry:
    module_ir = parse_module(input_path)
    vhdl_text = emit_vhdl(module_ir)

    name_map = NameMap.build(module_ir)
    namemap_payload = {}
    for signal in module_ir.signals:
        namemap_payload[signal.name] = name_map.signal(signal.name)
    namemap_payload.update(_instantiate.dropped_parameter_overrides(module_ir))
    namemap_text = json.dumps(dict(sorted(namemap_payload.items())), indent=2) + "\n"

    # The output name follows the *input file's* own stem, never the
    # module name declared inside it: `mkAxisTransportLayer.v` contains a
    # module named `mkAxiSTransportLayer` (capital S), and the next phase
    # expects the output at `mkAxisTransportLayer.vhd`. This is a no-op for
    # every one of the thirteen vendored blue-lib files, where the stem and
    # the module name are identical.
    stem = input_path.stem
    vhdl_path = _resolve_output_path(out_dir, f"{stem}.vhd")
    namemap_path = _resolve_output_path(out_dir, f"{stem}.namemap.json")

    _atomic_write(vhdl_path, vhdl_text)
    _atomic_write(namemap_path, namemap_text)

    return manifest_entry(input_path, vhdl_path.name, vhdl_text)


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    exit_code = 0
    entries: list[ManifestEntry] = []
    for raw_input in args.inputs:
        input_path = Path(raw_input)
        try:
            entries.append(_process_one(input_path, out_dir))
        except UnsupportedConstruct as exc:
            print(str(exc), file=sys.stderr)
            exit_code = 1

    if args.manifest is not None:
        if exit_code == 0:
            # A manifest that records a run which partly failed would be
            # worse than no manifest: only write when every input in this
            # invocation succeeded.
            manifest_path = Path(args.manifest)
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write(manifest_path, build_manifest(entries))
        else:
            print(
                f"refusing to write manifest {args.manifest}: at least one input failed",
                file=sys.stderr,
            )

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
