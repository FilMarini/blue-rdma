# Test methodology:
# - Sweep: every behavior `component_declarations`/`instantiations` own:
#   component deduplication by module name, deterministic sort-by-name
#   order independent of instantiation order, generic-clause omission for
#   a parameterless module, the naming rule's generic derivation and
#   `guarded` drop, direction inference from the referencing module's own
#   driven-name set, the open-port idiom, and the `__main__.py`
#   output-file-naming rule this same plan changes.
# - Stimulus: synthetic modules written to `tmp_path`, never to
#   `tests/vendor/`, which stays pinned at exactly the thirteen real
#   surf files. `test_instantiate_vendor_directory_is_still_thirteen_files`
#   guards that count directly.
# - Checks: text-level assertions on the rendered VHDL (never a golden
#   file, since no committed golden exists yet for a synthetic input), plus
#   the real command-line entry point for the output-naming test.
# - Timing: None. This file launches no simulator.
from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from tools.bsc2vhdl.emit import emit_vhdl
from tools.bsc2vhdl.instantiate import component_declarations, dropped_parameter_overrides, instantiations
from tools.bsc2vhdl.parser import parse_module

_REPO_ROOT = Path(__file__).resolve().parents[3]

_PARAM_MOD_INSTANCES = """\
   ParamMod #(.width(32'd8), .guarded(1'd1)) u_first(.CLK(CLK), .RST(RST), .D_IN(D_IN), .D_OUT(mid_data));
   ParamMod #(.width(32'd8), .guarded(1'd1)) u_second(.CLK(CLK), .RST(RST), .D_IN(mid_data), .D_OUT(D_OUT));
"""

_FLAG_MOD_INSTANCE = "   FlagMod u_flag(.CLK(CLK), .FLAG(mid_flag), .UNUSED_OUT());\n"


def _probe_source(*, instances_first: str, instances_second: str) -> str:
    return f"""\
module InstantiateProbe(CLK, RST, D_IN, D_OUT, mid_flag_out);
   input CLK;
   input RST;
   input [7:0] D_IN;
   output [7:0] D_OUT;
   output mid_flag_out;

   wire [7:0] mid_data;
   wire mid_flag;

   assign mid_flag_out = mid_flag;

{instances_first}{instances_second}
endmodule
"""


@dataclass
class _Ctx:
    """A minimal stand-in for `emit.py`'s `_EmitContext`, exposing exactly
    the one attribute `instantiations` reads: the identity mapping is
    correct here, since this file checks structure (component count,
    generic presence, absence of `entity`), never exact renamed spelling,
    which `test_emit_golden.py`'s real-pipeline tests already cover."""

    def name_for(self, name: str) -> str:
        return name


def _parse(tmp_path: Path, source: str) -> object:
    path = tmp_path / "InstantiateProbe.v"
    path.write_text(source)
    return parse_module(path)


def test_component_declarations_dedupes_by_module_and_sorts_by_name(tmp_path: Path) -> None:
    module_ir = _parse(tmp_path, _probe_source(instances_first=_PARAM_MOD_INSTANCES, instances_second=_FLAG_MOD_INSTANCE))
    text = "\n".join(component_declarations(module_ir, _Ctx()))

    assert text.count("component ParamMod is") == 1
    assert text.count("component FlagMod is") == 1
    assert text.index("component FlagMod is") < text.index("component ParamMod is")


def test_component_declarations_omit_generic_clause_when_module_has_none(tmp_path: Path) -> None:
    module_ir = _parse(tmp_path, _probe_source(instances_first=_PARAM_MOD_INSTANCES, instances_second=_FLAG_MOD_INSTANCE))
    lines = component_declarations(module_ir, _Ctx())
    text = "\n".join(lines)

    flag_start = text.index("component FlagMod is")
    flag_end = text.index("end component;", flag_start)
    flag_block = text[flag_start:flag_end]
    assert "generic (" not in flag_block

    param_start = text.index("component ParamMod is")
    param_end = text.index("end component;", param_start)
    param_block = text[param_start:param_end]
    assert "generic (" in param_block
    assert "WIDTH_G : positive" in param_block


def test_component_declarations_never_emit_entity(tmp_path: Path) -> None:
    module_ir = _parse(tmp_path, _probe_source(instances_first=_PARAM_MOD_INSTANCES, instances_second=_FLAG_MOD_INSTANCE))
    text = "\n".join(component_declarations(module_ir, _Ctx()) + instantiations(module_ir, _Ctx()))
    assert "entity" not in text


def test_instantiations_emit_one_labelled_instantiation_per_instance(tmp_path: Path) -> None:
    module_ir = _parse(tmp_path, _probe_source(instances_first=_PARAM_MOD_INSTANCES, instances_second=_FLAG_MOD_INSTANCE))
    text = "\n".join(instantiations(module_ir, _Ctx()))

    assert text.count("u_first : ParamMod") == 1
    assert text.count("u_second : ParamMod") == 1
    assert text.count("u_flag : FlagMod") == 1
    assert text.count("generic map (") == 2
    assert text.count("port map (") == 3


def test_dropped_guarded_override_has_no_generic_map_association(tmp_path: Path) -> None:
    module_ir = _parse(tmp_path, _probe_source(instances_first=_PARAM_MOD_INSTANCES, instances_second=_FLAG_MOD_INSTANCE))
    text = "\n".join(instantiations(module_ir, _Ctx()))
    assert "GUARDED_G" not in text
    assert "guarded" not in text.lower()


def test_dropped_guarded_override_is_recorded_in_the_namemap_helper(tmp_path: Path) -> None:
    module_ir = _parse(tmp_path, _probe_source(instances_first=_PARAM_MOD_INSTANCES, instances_second=_FLAG_MOD_INSTANCE))
    dropped = dropped_parameter_overrides(module_ir)
    assert dropped["u_first.guarded"]
    assert dropped["u_second.guarded"]
    assert "u_flag.guarded" not in dropped


def test_unconnected_port_defaults_to_open_scalar_output(tmp_path: Path) -> None:
    module_ir = _parse(tmp_path, _probe_source(instances_first=_PARAM_MOD_INSTANCES, instances_second=_FLAG_MOD_INSTANCE))
    component_text = "\n".join(component_declarations(module_ir, _Ctx()))
    instantiation_text = "\n".join(instantiations(module_ir, _Ctx()))

    assert "UNUSED_OUT : out sl" in component_text
    assert "UNUSED_OUT => open" in instantiation_text


def test_direction_inferred_from_driven_names_matches_a_real_datapath(tmp_path: Path) -> None:
    """`ParamMod`'s own two instances chain `D_OUT` of `u_first` into `D_IN`
    of `u_second`. `D_IN`/`RST`/`CLK` are driven from outside this module
    (top-level inputs or, for `D_IN`, connected straight to one); `D_OUT`
    is never the target of anything but the instance itself. This is the
    exact shape `mkAxisTransportLayer.v`'s eight `FIFO2` instances take
    with their own `assign`-driven `D_IN`/`ENQ`/`DEQ`/`CLR` wires."""
    module_ir = _parse(tmp_path, _probe_source(instances_first=_PARAM_MOD_INSTANCES, instances_second=_FLAG_MOD_INSTANCE))
    component_text = "\n".join(component_declarations(module_ir, _Ctx()))

    param_start = component_text.index("component ParamMod is")
    param_end = component_text.index("end component;", param_start)
    param_block = component_text[param_start:param_end]

    assert "CLK  : in " in param_block or "CLK   : in " in param_block
    assert "D_IN" in param_block and ": in " in param_block.split("D_IN")[1].split(";")[0]
    assert "D_OUT" in param_block and ": out" in param_block.split("D_OUT")[1].split(";")[0]


def test_component_order_is_independent_of_instantiation_order(tmp_path: Path) -> None:
    forward = _parse(tmp_path, _probe_source(instances_first=_PARAM_MOD_INSTANCES, instances_second=_FLAG_MOD_INSTANCE))
    forward_text = "\n".join(component_declarations(forward, _Ctx()))

    reversed_tmp = tmp_path / "reversed"
    reversed_tmp.mkdir()
    reordered = _parse(
        reversed_tmp, _probe_source(instances_first=_FLAG_MOD_INSTANCE, instances_second=_PARAM_MOD_INSTANCES)
    )
    reordered_text = "\n".join(component_declarations(reordered, _Ctx()))

    assert forward_text == reordered_text


def test_instantiate_output_name_follows_file_stem(tmp_path: Path) -> None:
    source = """\
module InstantiateStemProbe(CLK);
   input CLK;
endmodule
"""
    input_path = tmp_path / "StemDiffersFromModule.v"
    input_path.write_text(source)
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    result = subprocess.run(
        [sys.executable, "-m", "tools.bsc2vhdl", str(input_path), "--out-dir", str(out_dir)],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr

    vhdl_path = out_dir / "StemDiffersFromModule.vhd"
    namemap_path = out_dir / "StemDiffersFromModule.namemap.json"
    assert vhdl_path.exists()
    assert namemap_path.exists()
    assert not (out_dir / "InstantiateStemProbe.vhd").exists()

    text = vhdl_path.read_text()
    assert "entity InstantiateStemProbe is" in text
    assert "end InstantiateStemProbe;" in text


def test_instantiate_output_name_is_a_no_op_for_the_vendored_corpus(vendor_dir: Path, tmp_path: Path) -> None:
    inputs = sorted(vendor_dir.glob("*.v"))
    result = subprocess.run(
        [sys.executable, "-m", "tools.bsc2vhdl", *[str(path) for path in inputs], "--out-dir", str(tmp_path)],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr

    expected_names = {path.stem for path in inputs}
    actual_names = {path.stem for path in tmp_path.glob("*.vhd")}
    assert actual_names == expected_names
    assert len(actual_names) == 13


def test_instantiate_vendor_directory_is_still_thirteen_files(vendor_dir: Path) -> None:
    assert len(sorted(vendor_dir.glob("*.v"))) == 13


def test_dropped_parameter_overrides_key_shape(tmp_path: Path) -> None:
    module_ir = _parse(tmp_path, _probe_source(instances_first=_PARAM_MOD_INSTANCES, instances_second=_FLAG_MOD_INSTANCE))
    dropped = dropped_parameter_overrides(module_ir)
    # JSON-serializable, matching the shape __main__.py merges into the
    # namemap sidecar payload.
    json.dumps(dropped)


def test_emit_vhdl_places_component_declarations_before_begin_never_after(tmp_path: Path) -> None:
    module_ir = _parse(tmp_path, _probe_source(instances_first=_PARAM_MOD_INSTANCES, instances_second=_FLAG_MOD_INSTANCE))
    text = emit_vhdl(module_ir)

    begin_index = text.index("\nbegin\n")
    component_index = text.index("component FlagMod is")
    assert component_index < begin_index

    instantiation_index = text.index("u_first : ParamMod")
    assert instantiation_index > begin_index


def test_emit_vhdl_never_emits_entity_work_or_entity_surf_for_instances(tmp_path: Path) -> None:
    module_ir = _parse(tmp_path, _probe_source(instances_first=_PARAM_MOD_INSTANCES, instances_second=_FLAG_MOD_INSTANCE))
    text = emit_vhdl(module_ir)
    assert "entity work." not in text
    assert "entity surf." not in text
