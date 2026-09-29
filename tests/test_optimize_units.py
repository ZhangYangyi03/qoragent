"""The search bookkeeping -- verdicts, reduction, and the ledger."""

import os

from qoragent import optimize, synth


def _metric(cells):
    return synth.Metric(cells=cells, cell_breakdown={}, wires=0, wire_bits=0)


def test_reduction_is_computed_from_measured_cells():
    r = optimize.SearchResult("t", _metric(1000), _metric(250), [])
    assert abs(r.reduction - 0.75) < 1e-9


def test_zero_baseline_does_not_divide_by_zero():
    assert optimize.SearchResult("t", _metric(0), _metric(0), []).reduction == 0.0


def test_only_kept_steps_count_as_kept():
    steps = [optimize.Step("a", "why", _metric(10), True, "KEPT"),
             optimize.Step("b", "why", _metric(5), False, "REJECTED_NOT_EQUIVALENT")]
    r = optimize.SearchResult("t", _metric(20), _metric(10), steps)
    assert [s.name for s in r.kept] == ["a"]


def test_report_lists_every_candidate_with_its_verdict():
    steps = [optimize.Step("abc", "why", _metric(674), True, "KEPT"),
             optimize.Step("bad", "why", _metric(500), False,
                           "REJECTED_NOT_EQUIVALENT")]
    text = optimize.report(optimize.SearchResult("mac", _metric(2190),
                                                 _metric(674), steps))
    assert "REJECTED_NOT_EQUIVALENT" in text
    assert "69.2% fewer" in text


def test_candidate_list_compiles_to_a_usable_pass_string():
    # every candidate must be a sequence of yosys commands, one per line
    for name, passes, why in optimize.CANDIDATES:
        assert passes.strip(), name
        assert why.strip(), name
        assert "\\n" not in passes, "passes must be real newlines"
