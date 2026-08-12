"""Identifier renaming for internal signals: camelCase plus a name-map sidecar.

Ports keep their Verilog spelling verbatim (`NameMap.port` is the identity
function and must never consult the camelCase transform, because the
equivalence harness derives its port list from the Verilog and drives both
simulators from that single spelling). Internal signals are fully renamed.
The rename transform, locked here: split the original name on underscore,
drop empty tokens, lowercase the first token entirely, capitalize each
later token's first character and lowercase the rest of that token, then
join with no separator. `not_ring_full` becomes `notRingFull`, `data0_reg`
becomes `data0Reg`, and the internal register `Q_OUT` becomes `qOut`.

Ports are reserved in the namespace before any internal name is placed,
and all collision detection is case-insensitive because VHDL identifiers
are. The collision-suffix branch is a documented stub for a later plan.
"""
from __future__ import annotations

import json
from pathlib import Path

from .reserved_words import VHDL_RESERVED_WORDS


def _camel_case(name: str) -> str:
    tokens = [token for token in name.split("_") if token]
    if not tokens:
        return name.lower()
    first, *rest = tokens
    parts = [first.lower()]
    for token in rest:
        parts.append(token[0].upper() + token[1:].lower())
    return "".join(parts)


class NameMap:
    """Maps original Verilog internal names to collision-free VHDL names."""

    def __init__(self) -> None:
        self._signal_names: dict[str, str] = {}
        self._reserved: set[str] = set(VHDL_RESERVED_WORDS)

    @classmethod
    def build(cls, module_ir) -> "NameMap":
        name_map = cls()
        for port in module_ir.ports:
            name_map._reserved.add(port.name.lower())
        for signal in module_ir.signals:
            candidate = _camel_case(signal.name)
            key = candidate.lower()
            if key in name_map._reserved:
                name_map._resolve_collision(signal.name, candidate)
            name_map._reserved.add(key)
            name_map._signal_names[signal.name] = candidate
        return name_map

    def _resolve_collision(self, original: str, candidate: str) -> None:
        # Owned by a later plan: the disambiguating suffix must derive from
        # the original Verilog identifier, never from declaration position,
        # so an unrelated upstream signal can never renumber everything.
        raise NotImplementedError(
            f"name collision on {candidate!r} (from {original!r}); "
            "the collision-suffix resolver is implemented by a later plan"
        )

    def signal(self, verilog_name: str) -> str:
        return self._signal_names[verilog_name]

    def port(self, verilog_name: str) -> str:
        return verilog_name

    def write_sidecar(self, path: Path) -> None:
        payload = dict(sorted(self._signal_names.items()))
        Path(path).write_text(json.dumps(payload, indent=2) + "\n")
