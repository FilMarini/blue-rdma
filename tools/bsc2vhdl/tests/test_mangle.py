# Test methodology:
# - Sweep: `VHDL_RESERVED_WORDS`'s size and spot-checked membership;
#   `NameMap.build`'s four-step allocation (port reservation, camelCase
#   transform, case-insensitive collision grouping, name-derived
#   disambiguation) against synthetic modules built to exercise each step
#   in isolation, plus a corpus census over all thirteen vendored files.
# - Stimulus: synthetic `ports`/`signals` objects (plain `SimpleNamespace`
#   instances carrying only the `.name` attribute `NameMap.build` reads),
#   and the real vendored corpus, parsed directly with pyverilog (not
#   through `parser.py`, which does not yet handle every declaration shape
#   in the real corpus and is owned by a later plan).
# - Checks: every collision and disambiguation behavior named in the plan
#   is asserted by a dedicated test; the corpus census collects every
#   violation before asserting once, so one run names every offender.
# - Timing: None. This file launches no simulator.
from __future__ import annotations

import tempfile
from pathlib import Path
from types import SimpleNamespace

import pyverilog.vparser.ast as vast
import pytest
from pyverilog.vparser.parser import parse as _pyverilog_parse

from tools.bsc2vhdl import mangle as _mangle
from tools.bsc2vhdl.errors import UnsupportedConstruct
from tools.bsc2vhdl.mangle import NameMap
from tools.bsc2vhdl.reserved_words import VHDL_RESERVED_WORDS

_SPOT_CHECK_WORDS = [
    "guarded", "bus", "new", "reject", "sll", "srl", "rol", "ror", "xnor",
    "unaffected", "literal", "group", "assume", "context", "parameter",
    "property", "sequence", "vunit",
]


def _module(ports: list[str], signals: list[str], source_path: Path | None = None):
    return SimpleNamespace(
        ports=[SimpleNamespace(name=name) for name in ports],
        signals=[SimpleNamespace(name=name) for name in signals],
        source_path=source_path or Path("synthetic.v"),
    )


# --- VHDL_RESERVED_WORDS -----------------------------------------------


def test_vhdl_reserved_words_size() -> None:
    assert len(VHDL_RESERVED_WORDS) >= 117


def test_vhdl_reserved_words_spot_check() -> None:
    for word in _SPOT_CHECK_WORDS:
        assert word in VHDL_RESERVED_WORDS, f"{word!r} missing from VHDL_RESERVED_WORDS"


def test_vhdl_reserved_words_all_lowercase() -> None:
    assert all(word == word.lower() for word in VHDL_RESERVED_WORDS)


# --- reserved-word avoidance --------------------------------------------


def test_reserved_word_candidate_is_disambiguated() -> None:
    # "guarded" camelCases to itself (no underscore to split on) and
    # collides with the reserved word of the same spelling.
    name_map = NameMap.build(_module(ports=[], signals=["guarded"]))
    assert name_map.signal("guarded") != "guarded"
    assert name_map.signal("guarded").lower() not in VHDL_RESERVED_WORDS


def test_reserved_word_candidate_carries_the_name_derived_suffix() -> None:
    name_map = NameMap.build(_module(ports=[], signals=["guarded"]))
    assert name_map.signal("guarded") == "guarded" + _mangle._collision_suffix("guarded")


# --- case-insensitive collision grouping --------------------------------


def test_two_names_colliding_case_insensitively_are_both_suffixed() -> None:
    name_map = NameMap.build(_module(ports=[], signals=["foo_bar", "fooBar"]))
    fooBar_result = name_map.signal("foo_bar")
    fooBar2_result = name_map.signal("fooBar")
    assert fooBar_result != "fooBar"
    assert fooBar2_result != "foobar"
    assert fooBar_result.lower() != fooBar2_result.lower()


def test_no_collision_leaves_candidate_bare() -> None:
    name_map = NameMap.build(_module(ports=[], signals=["not_ring_full", "data0_reg"]))
    assert name_map.signal("not_ring_full") == "notRingFull"
    assert name_map.signal("data0_reg") == "data0Reg"


def test_internal_name_colliding_with_a_port_name_is_suffixed() -> None:
    # A signal whose camelCase candidate collides case-insensitively with a
    # port name must be disambiguated; the port itself is never touched.
    name_map = NameMap.build(_module(ports=["dOut"], signals=["D_OUT"]))
    assert name_map.port("dOut") == "dOut"
    assert name_map.signal("D_OUT") != "dOut"
    assert name_map.signal("D_OUT").lower() != "dout"


def test_suffixed_name_still_colliding_raises(monkeypatch) -> None:
    # Force two distinct originals to produce the same suffix, proving the
    # "raise rather than extend" rule fires on a genuine post-suffix
    # collision instead of silently accepting it.
    monkeypatch.setattr(_mangle, "_collision_suffix", lambda original: "_deadbf")
    with pytest.raises(UnsupportedConstruct, match="suffixed identifier collision"):
        NameMap.build(_module(ports=[], signals=["foo_bar", "fooBar"]))


# --- suffix is a pure function of the original name ---------------------


def test_collision_suffix_is_a_pure_function_of_the_original_name() -> None:
    # Called from two different module contexts, the suffix helper returns
    # the same string for the same original name: it is a function of the
    # name alone, never of position or of any other name in the module.
    first = _mangle._collision_suffix("not_ring_full")
    NameMap.build(_module(ports=[], signals=["unrelated_a", "unrelated_b", "not_ring_full"]))
    second = _mangle._collision_suffix("not_ring_full")
    assert first == second


def test_collision_suffix_is_underscore_plus_six_hex_chars() -> None:
    import re

    suffix = _mangle._collision_suffix("guarded")
    assert re.fullmatch(r"_[0-9a-f]{6}", suffix)


# --- port reservation ----------------------------------------------------


def test_port_names_pass_through_unchanged() -> None:
    name_map = NameMap.build(_module(ports=["CLK", "RST", "Q_OUT", "D_IN", "EN"], signals=[]))
    for port in ["CLK", "RST", "Q_OUT", "D_IN", "EN"]:
        assert name_map.port(port) == port


def test_port_name_never_rewritten_even_if_it_collides_with_a_reserved_word() -> None:
    name_map = NameMap.build(_module(ports=["guarded"], signals=[]))
    assert name_map.port("guarded") == "guarded"


# --- determinism under declaration reordering ---------------------------


def test_name_map_is_deterministic_under_signal_reordering(tmp_path: Path) -> None:
    forward = _module(ports=["CLK"], signals=["not_ring_full", "data0_reg", "guarded"])
    reversed_module = _module(ports=["CLK"], signals=["guarded", "data0_reg", "not_ring_full"])

    forward_path = tmp_path / "forward.json"
    reversed_path = tmp_path / "reversed.json"
    NameMap.build(forward).write_sidecar(forward_path)
    NameMap.build(reversed_module).write_sidecar(reversed_path)

    assert forward_path.read_bytes() == reversed_path.read_bytes()


# --- write_sidecar --------------------------------------------------------


def test_write_sidecar_is_sorted_two_space_indented_with_trailing_newline(tmp_path: Path) -> None:
    name_map = NameMap.build(_module(ports=[], signals=["zebra_reg", "alpha_reg"]))
    path = tmp_path / "sidecar.json"
    name_map.write_sidecar(path)
    text = path.read_text()

    assert text.endswith("\n")
    assert not text.endswith("\n\n")
    assert text.index('"alpha_reg"') < text.index('"zebra_reg"')
    assert '  "' in text  # two-space indent


# --- corpus census: no suffix fires on the real corpus today ------------


def _raw_module_names(path: Path) -> tuple[list[str], list[str]]:
    """Return (port names, internal Reg/Wire names) for `path`, parsed
    directly with pyverilog. Bypasses `parser.py`, which does not yet
    handle every declaration shape in the real corpus and is owned by a
    different task in this same plan; the census only needs the declared
    name population, not a working end-to-end parse.
    """
    ast_root, _directives = _pyverilog_parse(
        [str(path)], preprocess_define=[], debug=False, outputdir=tempfile.gettempdir()
    )
    module_def = [item for item in ast_root.description.definitions if isinstance(item, vast.ModuleDef)][0]
    port_names = [port.name for port in module_def.portlist.ports]

    signal_names: list[str] = []

    def _walk(node) -> None:
        if isinstance(node, (vast.Reg, vast.Wire)):
            signal_names.append(node.name)
        for child in node.children():
            _walk(child)

    for item in module_def.items:
        _walk(item)
    return port_names, signal_names


def _vendor_files(vendor_dir: Path) -> list[Path]:
    files = sorted(vendor_dir.glob("*.v"))
    assert len(files) == 13, f"expected thirteen vendored Verilog files, found {len(files)}: {files}"
    return files


def test_corpus_census_zero_collision_suffixes_fire(vendor_dir: Path) -> None:
    failures: list[str] = []
    for path in _vendor_files(vendor_dir):
        port_names, signal_names = _raw_module_names(path)
        module_ir = _module(ports=port_names, signals=signal_names, source_path=path)
        name_map = NameMap.build(module_ir)

        for original in signal_names:
            emitted = name_map.signal(original)
            if emitted != _mangle._camel_case(original):
                failures.append(f"{path.name}: {original!r} -> {emitted!r} carries a collision suffix")

        emitted_lower = [name_map.signal(name).lower() for name in signal_names]
        if len(emitted_lower) != len(set(emitted_lower)):
            failures.append(f"{path.name}: two originals emit the same VHDL name case-insensitively")

        for emitted in emitted_lower:
            if emitted in VHDL_RESERVED_WORDS:
                failures.append(f"{path.name}: emitted name {emitted!r} is a VHDL reserved word")

        port_lower = {name.lower() for name in port_names}
        for emitted in emitted_lower:
            if emitted in port_lower:
                failures.append(f"{path.name}: emitted internal name {emitted!r} collides with a port name")

    assert failures == [], "\n".join(failures)
