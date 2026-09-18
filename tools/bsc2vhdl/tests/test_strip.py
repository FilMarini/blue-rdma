# Test methodology:
# - Sweep: `is_simulation_only`'s three shapes (an `Initial` node
#   unconditionally, a display-bearing `Always` block whose non-local
#   assignment targets are disjoint from module storage, and the
#   `DelayStatement`/`TaskCall` completeness cases that occur nowhere in
#   the corpus), plus a corpus-wide sweep of `partition_always_blocks`
#   across all thirteen vendored files.
# - Stimulus: the real vendored corpus, parsed through the real
#   `parse_module`, plus one hand-built synthetic `Always` node for the
#   block-local-declaration shape a real fixture cannot isolate on its
#   own.
# - Checks: a set comparison of every module-level register assigned
#   before and after stripping (never a count, since a count passes when
#   one register is dropped and another double-counted), and a mutation
#   proof that widening the predicate is actually caught by that
#   comparison.
# - Timing: None. This file launches no simulator.
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pyverilog.vparser.ast as vast

from tools.bsc2vhdl.parser import parse_module
from tools.bsc2vhdl.strip import is_simulation_only, partition_always_blocks

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _vendor_files(vendor_dir: Path) -> list[Path]:
    files = sorted(vendor_dir.glob("*.v"))
    assert len(files) == 13, f"expected thirteen vendored Verilog files, found {len(files)}: {files}"
    return files


def test_is_simulation_only_true_for_initial_node() -> None:
    node = vast.Initial(vast.Block([]))
    assert is_simulation_only(node) is True


def test_is_simulation_only_true_for_delay_and_task_call() -> None:
    assert is_simulation_only(vast.DelayStatement(vast.IntConst("1"))) is True
    assert is_simulation_only(vast.TaskCall("my_task", [])) is True


def test_is_simulation_only_false_for_a_functional_always_block(vendor_dir: Path) -> None:
    module_ir = parse_module(vendor_dir / "FIFO2.v")
    kept, _dropped = partition_always_blocks(module_ir)
    # The data-path always block (data0_reg/data1_reg) is one of the two
    # surviving blocks; neither writes only block-local storage nor
    # contains a `$display`.
    assert len(kept) == 2


def test_is_simulation_only_display_block_with_block_local_targets_only() -> None:
    # A hand-built `Always` block reproducing the shape every corpus
    # display-bearing block takes: a `$display` call, and its only
    # assignment target (`flag`) is declared inside the block itself, not
    # at module scope. `declared_storage` here deliberately includes an
    # unrelated module-level name to prove the check is about *this*
    # block's own targets, not merely "no display block ever touches
    # anything real".
    flag_decl = vast.Decl([vast.Reg("flag")])
    system_call = vast.SystemCall("display", [vast.StringConst('"warn"')])
    display_stmt = vast.SingleStatement(system_call)
    assign_flag = vast.BlockingSubstitution(vast.Lvalue(vast.Identifier("flag")), vast.Rvalue(vast.IntConst("1")))
    body = vast.Block([flag_decl, assign_flag, display_stmt])
    node = vast.Always(vast.SensList([vast.Sens(vast.Identifier("CLK"), "posedge")]), body)

    assert is_simulation_only(node, declared_storage=frozenset({"some_other_reg"})) is True


def test_is_simulation_only_display_block_touching_module_storage_is_kept() -> None:
    # Same shape, except the block's assignment target IS declared at
    # module scope (never locally): a rule that ignored this distinction
    # would silently delete synthesis-relevant behavior that happens to
    # sit next to a display call.
    system_call = vast.SystemCall("display", [vast.StringConst('"warn"')])
    display_stmt = vast.SingleStatement(system_call)
    assign_real = vast.BlockingSubstitution(
        vast.Lvalue(vast.Identifier("real_reg")), vast.Rvalue(vast.IntConst("1"))
    )
    body = vast.Block([assign_real, display_stmt])
    node = vast.Always(vast.SensList([vast.Sens(vast.Identifier("CLK"), "posedge")]), body)

    assert is_simulation_only(node, declared_storage=frozenset({"real_reg"})) is False


def test_strip_drops_exactly_the_display_blocks(vendor_dir: Path) -> None:
    # Real per-file counts, verified directly against the vendored corpus:
    # every one of the eight real `$display` calls sits in exactly one
    # always block per file (FIFO2.v and FIFO20.v each carry a single
    # `error_checks` block holding two calls each; SizedFIFO.v's
    # `error_checks` block holds two of its four calls, the other two
    # living inside its `parameter_assertions` *initial* block, which
    # `partition_always_blocks` never touches since it partitions
    # `always_blocks` only -- `module_ir.initials` is the parser's own,
    # already-unconditional list). The plan's own acceptance-criteria text
    # names counts of 2/2/4; those describe display-*call* counts, not
    # dropped-*block* counts, and do not match a block-count reading of
    # the real corpus. See this plan's SUMMARY for the full account.
    expected = {"FIFO2.v": 1, "FIFO20.v": 1, "SizedFIFO.v": 1, "RegN.v": 0}
    for name, want in expected.items():
        module_ir = parse_module(vendor_dir / name)
        _kept, dropped = partition_always_blocks(module_ir)
        assert len(dropped) == want, (name, len(dropped), want)

    for path in _vendor_files(vendor_dir):
        if path.name in expected:
            continue
        module_ir = parse_module(path)
        _kept, dropped = partition_always_blocks(module_ir)
        assert len(dropped) == 0, (path.name, len(dropped))


def test_strip_loses_no_synthesis_relevant_assignment(vendor_dir: Path) -> None:
    failures: list[str] = []
    for path in _vendor_files(vendor_dir):
        module_ir = parse_module(path)
        declared_storage = frozenset(signal.name for signal in module_ir.signals)
        before = set()
        for block in module_ir.always_blocks:
            before |= _assigned_module_storage(block, declared_storage)

        kept, _dropped = partition_always_blocks(module_ir)
        after = set()
        for block in kept:
            after |= _assigned_module_storage(block, declared_storage)

        if before != after:
            failures.append(f"{path.name}: lost {before - after!r}, gained {after - before!r}")

    assert failures == [], "\n".join(failures)


def _assigned_module_storage(node, declared_storage: frozenset[str]) -> set[str]:
    from tools.bsc2vhdl.strip import _assignment_targets

    return _assignment_targets(node) & declared_storage


def test_strip_mutation_proof_widening_predicate_is_caught(vendor_dir: Path) -> None:
    """A mutation proof, run in-process rather than by editing the source
    file: widening the predicate to treat any `IfStatement`-bearing always
    block as simulation-only reproduces the exact failure
    `test_strip_loses_no_synthesis_relevant_assignment` exists to catch,
    confirming that test can actually fail. `git diff --stat` after this
    test still reports no change to `strip.py`, since the widened
    predicate below is local to this test and never written to disk."""
    module_ir = parse_module(vendor_dir / "FIFO2.v")
    declared_storage = frozenset(signal.name for signal in module_ir.signals)

    def _too_greedy(node) -> bool:
        return isinstance(node, vast.Always) and _contains_if(node.statement)

    before = set()
    for block in module_ir.always_blocks:
        before |= _assigned_module_storage(block, declared_storage)

    kept = [block for block in module_ir.always_blocks if not _too_greedy(block)]
    after = set()
    for block in kept:
        after |= _assigned_module_storage(block, declared_storage)

    assert before != after, "the too-greedy predicate should have lost a real register but did not"


def _contains_if(node) -> bool:
    if isinstance(node, vast.IfStatement):
        return True
    return any(_contains_if(child) for child in node.children())


def test_strip_never_reads_source_text_or_uses_regex() -> None:
    strip_source = (_REPO_ROOT / "tools" / "bsc2vhdl" / "strip.py").read_text()
    for forbidden in ("read_text", "readlines", "open(", "re.search", "re.match", "re.compile"):
        assert forbidden not in strip_source, forbidden


def test_strip_partition_always_blocks_corpus_counts(vendor_dir: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "\n".join(
                [
                    "from pathlib import Path",
                    "from tools.bsc2vhdl.parser import parse_module",
                    "from tools.bsc2vhdl.strip import partition_always_blocks",
                    f"v = Path({str(vendor_dir)!r})",
                    "for n, want in (('FIFO2.v', 1), ('FIFO20.v', 1), ('SizedFIFO.v', 1), ('RegN.v', 0)):",
                    "    kept, dropped = partition_always_blocks(parse_module(v / n))",
                    "    assert len(dropped) == want, (n, len(dropped), want)",
                    "print('ok')",
                ]
            ),
        ],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"
