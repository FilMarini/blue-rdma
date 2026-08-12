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

Ports are reserved in the namespace before any internal name is placed, and
all collision detection is case-insensitive because VHDL identifiers are.
`NameMap.build` allocates names in four steps, in this fixed order, because
the order is what makes the result independent of declaration order:

1. Reserve every port name verbatim. Ports are never transformed or
   suffixed.
2. Transform every internal name with the locked camelCase rule above,
   producing one candidate per original name.
3. Group the candidates by their lowercase form. A candidate whose
   lowercase form is a VHDL reserved word, or matches a reserved port name,
   is treated as its own group of one that needs disambiguation, because
   case-insensitive comparison is what VHDL's analyzer actually does.
4. Disambiguate: every member of a group that needs disambiguation
   receives a suffix that is a pure function of its own original Verilog
   name (never of position, never of any other name in the group), so one
   new upstream signal can never renumber every name in a file. A suffixed
   name that still collides raises `UnsupportedConstruct` naming both
   originals, because a real hash-prefix collision inside one module means
   something is wrong that a longer suffix would only hide.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .errors import UnsupportedConstruct
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


def _collision_suffix(original: str) -> str:
    """Return the disambiguating suffix for `original`.

    A pure function of the original Verilog identifier alone: an
    underscore followed by the first six hexadecimal characters of the
    SHA-256 digest of that name. Never a function of declaration order or
    of any other name in the module, so the suffix is provably the same
    string no matter which module context it is computed from.
    """
    digest = hashlib.sha256(original.encode()).hexdigest()
    return f"_{digest[:6]}"


class NameMap:
    """Maps original Verilog internal names to collision-free VHDL names."""

    def __init__(self) -> None:
        self._signal_names: dict[str, str] = {}

    @classmethod
    def build(cls, module_ir) -> "NameMap":
        name_map = cls()

        # Step one: reserve every port name verbatim.
        reserved_lower = {port.name.lower() for port in module_ir.ports}

        # Step two: transform every internal name with the locked camelCase
        # rule, producing one candidate per original name.
        candidates = {signal.name: _camel_case(signal.name) for signal in module_ir.signals}

        # Step three: group candidates by lowercase form. A group needing
        # disambiguation is any group with more than one member, or any
        # single-member group whose candidate collides with a reserved word
        # or a reserved port name.
        groups: dict[str, list[str]] = {}
        for original, candidate in candidates.items():
            groups.setdefault(candidate.lower(), []).append(original)

        needs_suffix: set[str] = set()
        for key, originals in groups.items():
            if len(originals) > 1 or key in VHDL_RESERVED_WORDS or key in reserved_lower:
                needs_suffix.update(originals)

        # Step four: disambiguate. Every member of a group needing
        # disambiguation is suffixed, not just the later-declared ones, so
        # the result carries no ordering information at all.
        final_names: dict[str, str] = {}
        for original, candidate in candidates.items():
            if original in needs_suffix:
                final_names[original] = candidate + _collision_suffix(original)
            else:
                final_names[original] = candidate

        final_groups: dict[str, list[str]] = {}
        for original, final in final_names.items():
            final_groups.setdefault(final.lower(), []).append(original)
        for key, originals in final_groups.items():
            if len(originals) > 1:
                raise UnsupportedConstruct(
                    f"suffixed identifier collision on {key!r} between {originals!r}",
                    getattr(module_ir, "source_path", Path(".")),
                    0,
                )

        name_map._signal_names = final_names
        return name_map

    def signal(self, verilog_name: str) -> str:
        return self._signal_names[verilog_name]

    def port(self, verilog_name: str) -> str:
        return verilog_name

    def write_sidecar(self, path: Path) -> None:
        payload = dict(sorted(self._signal_names.items()))
        Path(path).write_text(json.dumps(payload, indent=2) + "\n")
