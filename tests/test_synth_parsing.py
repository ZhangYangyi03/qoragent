"""Metric parsing and the path bridge -- pure functions, testable without yosys."""

from qoragent import synth

STAT = """=== mac ===

   Number of wires:                350
   Number of wire bits:           3692
   Number of public wires:          10
   Number of memories:               0
   Number of processes:              0
   Number of cells:               2190
     $_AND_                       1050
     $_NOT_                         17
     $_OR_                         399
     $_SDFFE_PP0P_                  32
     $_XOR_                        692
"""


def test_stat_block_becomes_a_metric():
    m = synth.parse_stat(STAT)
    assert m.cells == 2190
    assert m.wires == 350
    assert m.wire_bits == 3692


def test_cell_breakdown_is_kept_not_just_the_total():
    m = synth.parse_stat(STAT)
    assert m.cell_breakdown["$_AND_"] == 1050
    assert m.cell_breakdown["$_XOR_"] == 692


def test_a_log_without_a_stat_block_is_not_a_zero_cost_run():
    # this is the exact failure mode of `yosys -q`: no stat, and a naive parser
    # would report 0 cells as a 100% improvement
    assert synth.parse_stat("read_verilog x.v\nERROR: no such file") is None


def test_win_path_maps_to_wsl_mount():
    assert synth.win_to_wsl(r"D:\\bench\\rtl\\mac.v") == "/mnt/d/bench/rtl/mac.v"


def test_separator_free_string_still_yields_a_log():
    # yosys emits 'Filename' style paths with forward slashes too
    assert synth.win_to_wsl("/tmp/x.v") == "/tmp/x.v"


def test_equivalence_script_names_both_modules():
    s = synth.equivalence_script("a.v", "b.v", "gold", "gate")
    assert "equiv_make gold gate equiv" in s
    assert "equiv_status -assert" in s, (
        "without -assert yosys exits 0 on a failed proof, which would let a "
        "broken optimisation through")
