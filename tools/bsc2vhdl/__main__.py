"""Command-line entry point: `python -m tools.bsc2vhdl <inputs...> --out-dir DIR`.

Takes explicit input files and an explicit `--out-dir` and writes nowhere
else: no surf path and no default output directory are baked in. For each
input, the whole VHDL text and the whole name-map JSON are built in memory
first; only when both are complete are they written to a temporary file in
the target directory and moved into place with `os.replace`. A refused
construct prints its message to stderr, writes nothing for that input, and
the process continues to the remaining inputs before exiting nonzero.

`--survey` switches to census mode: every input is walked with
`survey_module` instead of emitted, `--out-dir` is not needed and no
directory is ever created, and every out-of-subset construct in a file is
reported rather than only the first. A completed census exits 0 even when
it found refusals, since finding refusals is a successful census; the
machine-readable signal is the printed total line, not the exit status. A
genuine tool error (an unreadable file, a pyverilog parse failure) still
propagates and exits nonzero. `--survey` and `--manifest` are mutually
exclusive: a census produces no outputs to record.

`--manifest-merge` (requires `--manifest`, mutually exclusive with
`--survey`) reads the manifest already at `--manifest`, if one exists, and
replaces or adds only the keys this invocation's own inputs produced,
leaving every other key untouched. Without it, `--manifest` is overwritten
with only this invocation's entries, exactly as before. `--out-dir` accepts
only one directory per invocation, so a manifest spanning two output
directories (a run over one directory, then a second run over another) is
produced by two invocations, the second with `--manifest-merge`. The
partial-run refusal holds in both modes: if any input in the invocation
failed, no manifest is written at all, merged or not.
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
from .parser import parse_module, survey_module
from .provenance import ManifestEntry, build_manifest, manifest_entry, merge_manifest


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m tools.bsc2vhdl")
    parser.add_argument("inputs", nargs="+", help="one or more BSC-generated .v files")
    parser.add_argument(
        "--out-dir", default=None, help="directory to write .vhd and .namemap.json output into"
    )
    parser.add_argument("--manifest", default=None, help="path to write a provenance manifest JSON")
    parser.add_argument(
        "--manifest-merge",
        action="store_true",
        help=(
            "merge this invocation's entries into the manifest named by --manifest instead of "
            "overwriting it: every entry this invocation did not produce is preserved verbatim"
        ),
    )
    parser.add_argument(
        "--survey",
        action="store_true",
        help="census mode: report every out-of-subset construct per input, writing nothing",
    )
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


def _run_survey(inputs: list[str]) -> int:
    """Census mode: report every out-of-subset construct per input and
    write nothing. Returns 0 unconditionally; a completed census is a
    successful census regardless of how many refusals it found."""
    total = 0
    for raw_input in inputs:
        refusals = survey_module(Path(raw_input))
        for refusal in refusals:
            print(str(refusal))
        print(f"survey: {len(refusals)} refusal(s) in {raw_input}")
        total += len(refusals)
    print(f"survey total: {total} refusal(s) across {len(inputs)} file(s)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.manifest_merge and args.manifest is None:
        parser.error("--manifest-merge requires --manifest")
    if args.manifest_merge and args.survey:
        parser.error("--manifest-merge and --survey cannot be combined: a census produces no entries to merge")

    if args.survey:
        if args.manifest is not None:
            parser.error("--survey and --manifest cannot be combined: a census produces no outputs to record")
        return _run_survey(args.inputs)

    if args.out_dir is None:
        parser.error("--out-dir is required unless --survey is given")

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
            # invocation succeeded. This guarantee holds in both modes below.
            manifest_path = Path(args.manifest)
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            if args.manifest_merge:
                try:
                    existing_entries = json.loads(manifest_path.read_text())["entries"]
                except FileNotFoundError:
                    existing_entries = {}
                manifest_text = merge_manifest(existing_entries, entries)
            else:
                manifest_text = build_manifest(entries)
            _atomic_write(manifest_path, manifest_text)
        else:
            print(
                f"refusing to write manifest {args.manifest}: at least one input failed",
                file=sys.stderr,
            )

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
