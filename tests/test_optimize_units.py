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


def test_a_candidate_that_could_not_be_measured_is_not_reported_as_too_big():
    """Two verdicts, not one. A run with no stat block has been shown to be
    unmeasured, not shown to be larger, and REJECTED_NOT_SMALLER claims a
    comparison that never happened. Measured: `dfflegalize` on the mac exits
    cleanly and prints no stat block at all.
    """
    from qoragent import synth as _synth

    class FakeSynth:
        calls = 0
        def run_synth(self, rtl, top, body, wd, timeout=300, **kw):
            FakeSynth.calls += 1
            if FakeSynth.calls == 1:                     # the baseline
                return _synth.SynthResult(True, _synth.Metric(cells=100), None, "stat", body)
            return _synth.SynthResult(False, None, None, "no stat here", body)

    real = optimize.synth.run_synth
    optimize.synth.run_synth = FakeSynth().run_synth
    try:
        r = optimize.search("x.v", "t", "wd", candidates=[("bad", "opt", "why")])
    finally:
        optimize.synth.run_synth = real
    assert r.steps[0].verdict == "FAILED"
    assert r.steps[0].verdict != "REJECTED_NOT_SMALLER"
    assert "stat" in r.steps[0].detail
