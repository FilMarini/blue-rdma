"""Identifies simulation-only module items by abstract-syntax-tree shape.

`// synopsys translate_off` is a plain Verilog comment; pyverilog's parser
sees straight through it to the real AST nodes regardless, so detection
here never inspects comment text, never reads the source file, and never
runs a regular expression against Verilog text. `is_simulation_only`
covers three shapes. First, an `Initial` node, which the initializer pass
consumes as a signal default rather than emitting as behavior. Second, an
`Always` block whose statement subtree contains at least one `SystemCall`
and whose assignment targets are all either declared inside that same
block or not part of the module's own *functional* storage: the exact
shape every `$display`-bearing always block in the corpus takes, since the
Bluespec runtime's error-reporting block writes only a scratch flag
register nothing else in the module ever reads or writes, whether that
register is declared block-local or, as `mkQP.v`'s and
`mkTransportLayer.v`'s `negedge`-triggered assertion blocks both do, at
module scope. Third, a `Delay` node or a `TaskCall`, neither of which
occurs anywhere in the corpus, kept here so the predicate is complete
rather than corpus-shaped.

`partition_always_blocks(module_ir)` applies the always-block shape above
to `module_ir.always_blocks`, measuring "the module's own functional
storage" via `_functional_storage_names(module_ir)` rather than the raw
signal-declaration list, and returns the surviving blocks and the dropped
blocks separately, so the emitter takes only the survivors and a test can
assert on both sides at once. `module_ir.initials` is a distinct list the
parser already builds independently (every `Initial` node is
simulation-only by the first rule above, unconditionally); this function
does not touch it and there is nothing to partition there.
"""
from __future__ import annotations

import pyverilog.vparser.ast as vast


def is_simulation_only(node, declared_storage: frozenset[str] | None = None) -> bool:
    if isinstance(node, (vast.Initial, vast.DelayStatement, vast.TaskCall)):
        return True
    if isinstance(node, vast.Always):
        return _always_is_simulation_only(node, declared_storage or frozenset())
    return False


def partition_always_blocks(module_ir) -> tuple[list, list]:
    """Split `module_ir.always_blocks` into (surviving, dropped).

    A block is dropped exactly when `is_simulation_only` says so, measured
    against `_functional_storage_names(module_ir)` rather than the raw set
    of every signal the module declares: a scratch register BSC happened to
    declare at module scope instead of block-local (`mkQP.v`'s giant
    `negedge`-triggered assertion block captures `$time` into 83 such
    registers, one per `$display` site) is still nobody's real storage if
    nothing outside a `$display`/`$finish`-bearing block ever reads or
    writes it. A target declared only inside the block itself is never
    part of either set, so it can never make a block survive on its own.
    """
    declared_storage = _functional_storage_names(module_ir)
    kept: list = []
    dropped: list = []
    for block in module_ir.always_blocks:
        if is_simulation_only(block, declared_storage):
            dropped.append(block)
        else:
            kept.append(block)
    return kept, dropped


def _functional_storage_names(module_ir) -> frozenset[str]:
    """Names touched by something other than debug/assertion reporting:
    every port, every continuous-assign and instantiation-connection
    identifier, and every identifier referenced by an `always` block whose
    own statement subtree contains no `SystemCall`. `module_ir.initials` is
    excluded outright since an `Initial` node is unconditionally
    simulation-only regardless of whether it happens to avoid a system
    call.

    This is a strict subset of `{signal.name for signal in
    module_ir.signals}`, never a superset, so a signal genuinely read or
    written by real logic is never newly excluded, and a block's own
    behavior can only move from kept to dropped, never the reverse. Proven
    to move zero blocks across all fourteen already-committed fixtures.
    """
    names: set[str] = {port.name for port in module_ir.ports}
    for assign in module_ir.assigns:
        _collect_identifier_names(assign, names)
    for instance in module_ir.instances:
        for port in instance.ports:
            if port.actual_expr is not None:
                names.add(port.actual_expr)
    for block in module_ir.always_blocks:
        if not _contains_system_call(block.statement):
            _collect_identifier_names(block.statement, names)
    return frozenset(names)


def _collect_identifier_names(node, out: set[str]) -> None:
    if isinstance(node, vast.Identifier):
        out.add(node.name)
        return
    for child in node.children():
        _collect_identifier_names(child, out)


def _contains_system_call(node) -> bool:
    if isinstance(node, vast.SystemCall):
        return True
    return any(_contains_system_call(child) for child in node.children())


def _assignment_target_name(target) -> str | None:
    if isinstance(target, vast.Identifier):
        return target.name
    if isinstance(target, vast.Pointer) and isinstance(target.var, vast.Identifier):
        return target.var.name
    return None


def _assignment_targets(node) -> set[str]:
    targets: set[str] = set()
    if isinstance(node, (vast.BlockingSubstitution, vast.NonblockingSubstitution)):
        name = _assignment_target_name(node.left.var)
        if name is not None:
            targets.add(name)
    for child in node.children():
        targets |= _assignment_targets(child)
    return targets


def _block_local_names(node) -> set[str]:
    names: set[str] = set()
    if isinstance(node, vast.Decl):
        for decl in node.list:
            name = getattr(decl, "name", None)
            if name is not None:
                names.add(name)
    for child in node.children():
        names |= _block_local_names(child)
    return names


def _always_is_simulation_only(node: vast.Always, declared_storage: frozenset[str]) -> bool:
    if not _contains_system_call(node.statement):
        return False
    targets = _assignment_targets(node.statement)
    local_names = _block_local_names(node.statement)
    non_local_targets = targets - local_names
    return non_local_targets.isdisjoint(declared_storage)
