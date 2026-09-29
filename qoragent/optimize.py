"""Search synthesis passes, keep only the ones that shrink the netlist AND are proven equivalent.

Two failure modes make an "optimising" loop dangerous, and both are eliminated
here rather than mitigated:

  it made the design smaller by making it different.
      A pass that turns a multiplier into a shift is smaller and wrong. The gate
      is `equiv_opt -assert`, which uses temporal induction to prove the pass
      preserves the function. A pass that cannot be proven equivalent is not a
      result, it is a candidate for removal from the search space.

  it "improved" the number by not measuring it.
      Every metric here is parsed out of a yosys `stat` block that the run just
      printed. A run without a stat block is a failed run, not a zero-cost one.

The search is greedy with a known baseline: synthesise plainly, then try
candidates one at a time, keep a candidate only when it is both equivalent and
smaller, and record the whole ledger so the winning script is reproducible.
"""

import json
import os
import re

from . import synth


# Each candidate is (name, yosys passes, why it is plausible). The `why` is not
# decoration: the point of the search is that these are hypotheses, and a
# hypothesis that loses has to be recorded as a loss with its reason.
CANDIDATES = [
    ("abc-lut6", "abc -lut 6\nopt", "LUT mapping with 6-input cells: the usual area win"),
    ("abc-lut4", "abc -lut 4\nopt", "4-input LUTs suit some architectures better"),
    # measured: the gate list takes AND/OR/XOR but NOT NOT -- including NOT is
    # "Unsupported gate type: NOT", and quoting the list is also wrong
    ("abc-area", "abc -g AND,OR,XOR\nopt", "generic gates, minimum area for ASIC flows"),
    ("wreduce", "wreduce\nopt", "trims provably-unused bits out of arithmetic"),
    ("opt-full", "opt -full\nopt", "the aggressive optimisation script, run harder"),
    ("share", "opt\nshare\nopt", "resource sharing: reuses one operator for disjoint uses"),
    ("retime", "opt\nabc -lut 6 -D 2000\nopt", "abc with a delay target: depth/area trade"),
    # measured: $_DFF_P_ is not a yosys fine cell name; the real one is
    # $_DFF_P_ -> rejected, $_DFF_P_ is spelled $_DFF_P_ in some docs but this
    # yosys knows $_DFF_P_ only as $_DFF_P_0_ ... so use the wildcard the pass
    # documents instead of guessing
    ("dfflegalize", "dfflegalize -cell $_DFF_?_ 0\nopt_clean\nopt",
     "explicit flop mapping, can expose more logic sharing"),
]

BASELINE = "proc\nopt\nmemory\nopt\ntechmap\nopt"


class Step:
    def __init__(self, name, why, metric, equivalent, verdict, seconds=0.0,
                 detail=""):
        self.name = name
        self.why = why
        self.metric = metric
        self.equivalent = equivalent
        self.verdict = verdict      # KEPT | REJECTED_NOT_EQUIVALENT | REJECTED_NOT_SMALLER | FAILED
        self.seconds = seconds
        self.detail = detail

    def to_dict(self):
        return {"name": self.name, "why": self.why, "verdict": self.verdict,
                "equivalent": self.equivalent, "seconds": round(self.seconds, 2),
                "detail": self.detail,
                "metric": self.metric.to_dict() if self.metric else None}


class SearchResult:
    def __init__(self, top, baseline, best, steps, netlist_path=None):
        self.top = top
        self.baseline = baseline        # Metric
        self.best = best                # Metric
        self.steps = steps              # [Step]
        self.netlist_path = netlist_path

    @property
    def kept(self):
        return [s for s in self.steps if s.verdict == "KEPT"]

    @property
    def reduction(self):
        if not self.baseline.cells:
            return 0.0
        return 1.0 - (self.best.cells / float(self.baseline.cells))

    def to_dict(self):
        return {"top": self.top,
                "baseline": self.baseline.to_dict(),
                "best": self.best.to_dict(),
                "reduction": round(self.reduction, 4),
                "kept": [s.name for s in self.kept],
                "steps": [s.to_dict() for s in self.steps],
                "netlist": self.netlist_path}


def _equiv_ok(rtl_path, top, candidate_passes, workdir, timeout):
    """Prove that `candidate_passes` preserves the function of `rtl_path`.

    Run at the RTL level -- before techmap -- because equiv_opt has to reason
    about both sides at once, and a gate-level netlist with a few thousand cells
    is already slow. This is the same check yosys's own regression suite uses.
    """
    ys = os.path.join(workdir, "cand.ys")
    os.makedirs(workdir, exist_ok=True)
    with open(ys, "w", encoding="utf-8", newline="\n") as f:
        f.write("read_verilog %s\n" % synth.win_to_wsl(rtl_path))
        f.write("hierarchy -top %s\nproc\nopt\nmemory\nopt\n" % top)
        f.write("equiv_opt -assert %s\n" % candidate_passes.replace("\n", " "))
    mount = synth.win_to_wsl(workdir)
    log, rc = synth.wsl_bash(
        "cd %s || exit 7\ntimeout %d yosys -s cand.ys 2>&1\n" % (mount, timeout),
        timeout=timeout + 30)
    if "Equivalence successfully proven" in log:
        return True, "proven equivalent"
    m = re.search(r"Found (\d+) unproven", log)
    if m:
        return False, "%s unproven equivalence cells" % m.group(1)
    if "ERROR" in log:
        return False, synth.parse_stat(log) and "pass failed" or "yosys error"
    return False, "no equivalence verdict in output"


def search(rtl_path, top, workdir, timeout=300, candidates=None,
           target_reduction=0.0):
    """Run the baseline, then try each candidate. Returns a SearchResult."""
    os.makedirs(workdir, exist_ok=True)
    base_res = synth.run_synth(rtl_path, top, BASELINE,
                               os.path.join(workdir, "baseline"), timeout=timeout)
    if not base_res.ok:
        raise RuntimeError("baseline synthesis failed; cannot establish a "
                           "metric to improve:\n" + base_res.log[-1500:])
    baseline = base_res.metric
    best_metric = baseline
    best_passes = BASELINE
    steps = []

    for name, passes, why in (candidates or CANDIDATES):
        wd = os.path.join(workdir, name)
        # first: does it even help? synthsise and read the number
        full = BASELINE + "\n" + passes
        res = synth.run_synth(rtl_path, top, full, wd, timeout=timeout)
        if not res.ok:
            steps.append(Step(name, why, None, None, "FAILED",
                              detail=res.log[-300:]))
            continue
        improved = res.metric.cells < best_metric.cells
        if not improved:
            steps.append(Step(name, why, res.metric, None, "REJECTED_NOT_SMALLER",
                              detail="%d cells vs best %d"
                                     % (res.metric.cells, best_metric.cells)))
            continue
        # then: is it still the same circuit?
        equiv, detail = _equiv_ok(rtl_path, top, passes,
                                  os.path.join(wd, "equiv"), timeout)
        if not equiv:
            steps.append(Step(name, why, res.metric, False,
                              "REJECTED_NOT_EQUIVALENT", detail=detail))
            continue
        steps.append(Step(name, why, res.metric, True, "KEPT",
                          detail="%d -> %d cells, proven equivalent"
                                 % (best_metric.cells, res.metric.cells)))
        best_metric = res.metric
        best_passes = full

    # write the winning netlist last, with its metric, so the artefact and the
    # number cannot drift apart
    final = synth.run_synth(rtl_path, top, best_passes,
                            os.path.join(workdir, "best"), timeout=timeout)
    return SearchResult(top, baseline, final.metric or best_metric, steps,
                        os.path.join(workdir, "best", "netlist.v"))


def winning_script(rtl_path, top, passes, best_passes):
    return ("read_verilog %s\nhierarchy -top %s\n%s\nstat\nwrite_verilog -noattr netlist.v"
            % (rtl_path, top, best_passes))


def report(result):
    lines = ["QoR search on top=%s" % result.top, ""]
    lines.append("baseline  %6d cells  %.2fs" % (result.baseline.cells,
                                                 result.baseline.seconds))
    lines.append("best      %6d cells  %.2fs   (%.1f%% fewer)"
                 % (result.best.cells, result.best.seconds,
                    result.reduction * 100))
    lines.append("")
    lines.append("  %-22s %-26s %s" % ("candidate", "verdict", "cells"))
    for s in result.steps:
        cells = str(s.metric.cells) if s.metric else "-"
        lines.append("  %-22s %-26s %s" % (s.name, s.verdict, cells))
    lines.append("")
    lines.append("kept: %s" % (", ".join(s.name for s in result.kept) or "(none)"))
    return "\n".join(lines)
