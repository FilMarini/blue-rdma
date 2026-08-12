# bsc2vhdl

A purpose-built transpiler from BSC (Bluespec Compiler) 2023.01-generated
Verilog to surf-idiomatic, GHDL-clean VHDL. It knows only the narrow subset
of Verilog that BSC 2023.01 actually emits, not general Verilog, and it
takes explicit input files and an explicit output directory, with no
knowledge of any other repository baked in.

## Prerequisites

Install the pinned dependencies:

```
pip install -r tools/bsc2vhdl/requirements.txt
```

`iverilog` must also be on `PATH`. The parser is built on `pyverilog`, which
preprocesses every input by shelling out to `iverilog -E`; there is no pure-
Python preprocessing path. `pyverilog` is pinned to `1.3.0` deliberately,
matching the version this tool was proven against; bumping it is a real
change that needs re-verification against the corpus, not a routine upgrade.

## Invocation

```
python -m tools.bsc2vhdl <input.v> [<input.v> ...] --out-dir DIR [--manifest PATH] [--version]
```

- `<input.v> [...]`: one or more BSC-generated `.v` files. Every input is
  processed independently; a refusal on one does not stop the others (see
  Refusal behavior below).
- `--out-dir DIR` (required): the tool writes only into `DIR`, creating it
  if needed, and writes nowhere else. There is no default destination and
  no surf-path or surf-layout knowledge anywhere in the tool. Point it at a
  temporary directory for a scratch run, or directly at a surf checkout's
  fixture directory to regenerate a committed output in place.
- `--manifest PATH` (optional): writes a provenance manifest to `PATH`. See
  Provenance manifest below.
- `--version`: prints the tool's version and exits.

The output file name follows the *input file's own stem*, never the module
name declared inside it: `mkAxisTransportLayer.v` contains a module named
`mkAxiSTransportLayer` (capital S), and the output still lands at
`mkAxisTransportLayer.vhd`. The VHDL entity name inside that file is the
module name from the Verilog, unchanged.

## What lands in `--out-dir`

For each input file that transpiles successfully:

- One `<stem>.vhd` file: the translated VHDL.
- One `<stem>.namemap.json` sidecar: internal signals are renamed to surf
  camelCase during translation, and this sidecar is how a harness mismatch
  on a renamed signal traces back to the original Verilog identifier in one
  lookup.

If `--manifest PATH` was given and every input in the invocation succeeded,
one more file is written at `PATH` (see below).

## Refusal behavior

On any Verilog construct outside the supported subset, the tool names the
construct and its `file:line`, writes nothing for that input file, and
continues on to the remaining input files before exiting nonzero. There is
no lenient mode and no partial output: an input file either transpiles
completely or contributes nothing to `--out-dir`.

A refusal on a file that used to transpile cleanly is a signal, not a bug to
route around: it means BSC's own generated output changed in a way this
tool has not been taught, and the fix belongs in the tool.

## Supported subset

- Continuous `assign`.
- `always @(posedge CLK)`, synchronous with an active-low `RST_N` reset
  branch when the module has one, and a level-sensitive combinational
  `always @(...)` block with no clock at all.
- `case` and `casez`, including `casez`'s `?` don't-care bit patterns.
- Module instantiation, emitted as a VHDL `component` declaration plus a
  plain instantiation statement, never a direct `entity work.X` or
  `entity surf.X` reference.
- `parameter` overrides given by name at an instantiation site.
- `initial` block power-on values, translated into VHDL signal initializers
  rather than stripped; this is a deliberate synthesis-visible difference
  from the Verilog, since Vivado honors a VHDL signal initializer as FF
  INIT state (see the note below).
- `$display`, `#delay`, and `task` calls, all of them simulation-only inside
  BSC's own `ifdef` guards, are stripped without dropping the
  synthesis-relevant code that shares the same block.

## Phase 4 census: mkQP, mkTransportLayer, mkAxisTransportLayer

A `--survey` census over the three generated blue-rdma modules
(`mkQP.v`, `mkTransportLayer.v`, `mkAxisTransportLayer.v`) found exactly two
distinct out-of-subset construct names, both inside `always` sensitivity-list
handling. No other construct name appears anywhere in the census output.

| Construct | `mkQP.v` | `mkTransportLayer.v` | `mkAxisTransportLayer.v` | Representative `file:line` |
|-----------|---------:|----------------------:|--------------------------:|-----------------------------|
| `always` block with more than one sensitivity item | 153 | 24 | 0 | `mkTransportLayer.v:4364` |
| `always` block sensitivity edge `'negedge'` | 1 | 1 | 0 | `mkQP.v:24731` |
| **Total** | **154** | **25** | **0** |  |

Command run (from this repository's root, `$SURF` pointing at a surf checkout):

```
python -m tools.bsc2vhdl --survey \
    $SURF/ethernet/RoCEv2/blue-rdma/mkQP.v \
    $SURF/ethernet/RoCEv2/blue-rdma/mkTransportLayer.v \
    $SURF/ethernet/RoCEv2/blue-rdma/mkAxisTransportLayer.v
```

Output: `survey: 154 refusal(s) in .../mkQP.v`, `survey: 25 refusal(s) in
.../mkTransportLayer.v`, `survey: 0 refusal(s) in
.../mkAxisTransportLayer.v`, `survey total: 179 refusal(s) across 3 file(s)`,
exit 0.

**Is the multi-item level-sensitive `always` block the only gap, or merely
the first?** Merely the first. The census found one other distinct
construct name: an `always` block whose single sensitivity item is
`negedge` rather than `posedge` or `level` (`mkQP.v:24731` and
`mkTransportLayer.v:6691`, one occurrence each). `mkAxisTransportLayer.v`
triggers neither refusal. Both refusal shapes are raised from the same
sensitivity-list check (`_check_always_sensitivity` in `parser.py`); the
census's per-file totals (154 for `mkQP.v`, 25 for `mkTransportLayer.v`) are
each one higher than a count of multi-item blocks alone would suggest,
because each file also carries exactly one `negedge` block.

**Does an `initial`-shaped refusal appear for `mkTransportLayer.v` or
`mkQP.v`?** No. Neither file's `initial` block (`mkTransportLayer.v:6602`,
`mkQP.v:24562`) appears anywhere in the census output: `grep` for those two
line numbers in the captured census text returns nothing. `parse_module`'s
own item dispatch routes an `Initial` node through
`_strip.is_simulation_only` before it ever reaches a refusal check, so both
`initial` blocks reach the emit path without incident, the same as every
already-transpiled file that carries one.

**Exit-code behavior.** Without `--survey`, the tool exits 1 on a refusal
and writes nothing for the refused input file; a caller checking only the
exit status correctly detects that at least one input refused. With a
multi-file invocation (survey or otherwise), one exit code covers the whole
run, so per-file attribution still requires reading stdout/stderr rather
than the exit status alone.

**`// synopsys parallel_case` no-change finding, verified.** The corpus
carries 14 such pragma comments (4 in `mkTransportLayer.v`, 10 in `mkQP.v`,
0 in `mkAxisTransportLayer.v`). Verified by direct search that no module
under `tools/bsc2vhdl/` (including `caseconv.py`) contains the pragma
token anywhere:

```
grep -rn "parallel_case" tools/bsc2vhdl/
```

returns no matches. pyverilog strips comments before parsing, so the
pragma never reaches the AST `caseconv.py` walks; `caseconv.py`'s existing
plain-`case` path already renders these blocks as an ordered if/elsif
chain, which is exactly the first-match semantics Icarus simulates and the
equivalence gate compares. No emitter change is needed for these 14 blocks.

## Notable exclusions

- `generate` / `endgenerate`: refused. A census across every real BSC target
  this tool exists for found zero uses; the construct occurs nowhere in the
  generated output this tool targets, so no translation was ever built for
  it.
- `function`, `for`, `defparam`, `inout`: refused. None of BSC's own
  generated Verilog uses any of these, so, like `generate`, no translation
  exists.
- Anything else outside the subset above: refused by name and `file:line`
  rather than silently guessed at.

## Provenance manifest

`--manifest PATH` writes a JSON object, one entry per emitted file, of the
source Verilog's own file name, its SHA-256, the output file name, its
SHA-256, and the transpiler version. It is written once, only when every
input in the invocation succeeded, and its entries are sorted by source file
name with two-space indentation and a trailing newline, so a re-run at a
fixed tool version reproduces byte-identical manifest text. The digests are
integrity checks against accidental drift, never a security property.

## A known consequence: FF initial state

Because `initial`-block power-on values become VHDL signal initializers (see
Supported subset above), Vivado synthesizes each affected register with the
Bluespec pattern as its FF INIT state instead of the default zero. This is a
real, deliberate netlist difference against the original Verilog. It does
not change LUT or FF counts, only initial state, and it must be checked on
purpose at hardware sign-off rather than discovered there. A
`-- synthesis translate_off`-bracketed alternative, which would keep an
Icarus-matching simulation power-on with no synthesis-visible change, was
considered and declined in favor of this simpler emitter; it remains
available if the changed initial state ever turns out to matter on real
hardware.

## Regenerating the committed fixtures

The thirteen blue-lib primitives and `mkAxisTransportLayer` are committed as
test fixtures in the `surf` submodule under
`tests/ethernet/RoCEv2/transpiled/`, not in this repository. `$SURF` below
is that submodule's checkout root.

Regenerate the thirteen blue-lib fixtures in place:

```
python -m tools.bsc2vhdl $SURF/ethernet/RoCEv2/blue-lib/*.v \
    --out-dir $SURF/tests/ethernet/RoCEv2/transpiled
```

Regenerate the transport layer fixture in place:

```
python -m tools.bsc2vhdl $SURF/ethernet/RoCEv2/blue-rdma/mkAxisTransportLayer.v \
    --out-dir $SURF/tests/ethernet/RoCEv2/transpiled
```

Regenerate surf's provenance manifest (covers all fourteen fixtures above in
one file, since both sets are transpiled together in this invocation):

```
python -m tools.bsc2vhdl $SURF/ethernet/RoCEv2/blue-lib/*.v \
    $SURF/ethernet/RoCEv2/blue-rdma/mkAxisTransportLayer.v \
    --out-dir $SURF/tests/ethernet/RoCEv2/transpiled \
    --manifest $SURF/tests/ethernet/RoCEv2/transpiled/PROVENANCE.json
```

Regenerate this repository's own golden manifest, covering only the thirteen
vendored files this unit suite is hermetic against (discard the `.vhd`
output; only the manifest is committed here):

```
python -m tools.bsc2vhdl tools/bsc2vhdl/tests/vendor/*.v \
    --out-dir /tmp/bsc2vhdl-manifest-regen \
    --manifest tools/bsc2vhdl/tests/golden/manifest.json
```

Verify the result in each repository:

```
python -m pytest tools/bsc2vhdl/tests/test_provenance.py -q
```

```
cd $SURF && python -m pytest tests/ethernet/RoCEv2/test_TranspiledProvenance.py -q
```

## Running the test suite

From this repository's root:

```
python -m pytest tools/bsc2vhdl/tests -q
```

The suite is pure Python with no simulator dependency, except for a small
number of tests that additionally shell out to `ghdl` and to surf's `vsg`
linter against a surf checkout (located via the `BSC2VHDL_SURF_ROOT`
environment variable). Those tests skip themselves, with an explicit reason,
when no such checkout or pre-analyzed work library is present, so the suite
as a whole is runnable on a machine with no surf tree at all.
