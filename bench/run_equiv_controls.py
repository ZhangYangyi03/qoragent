"""The equivalence gate, tested in the direction that can only fail silently.

An optimisation gate is easy to test one way: hand it a broken circuit and check
it says no. That is the direction that fails loudly and gets noticed. The
direction that fails QUIETLY is the opposite one -- hand it a correct circuit and
see whether it still says yes. A gate that says no to everything looks like a
strict gate rather than a broken one, and it turns the whole search into a
program that never keeps anything.

Both directions are measured here, and both are checked in as RTL:

    mac_alt.v    the same multiply-accumulate, renamed
                 -> must be PROVEN. Positive control.
    mac_wrong.v  a multiply-accumulate with `+ c` dropped: 152 cells smaller
                 -> must be REJECTED. Negative control, and the honest version of
                 "reduced area by 7%".

Measured on this host, and the second number is the reason `equiv_induct` is in
the script: with `equiv_simple` alone the identical renamed circuit comes back
with 97 unproven cells -- the gate says NO to a circuit that is the same circuit.
An accumulator's state is only reachable by induction.

    python bench/run_equiv_controls.py             run both, needs yosys
    python bench/run_equiv_controls.py --replay    compare against the record
    python bench/run_equiv_controls.py --record    write the record
"""

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from qoragent import optimize, synth                    # noqa: E402

RTL = os.path.join(HERE, "rtl")
RECORD = os.path.join(HERE, "fixtures", "equiv_controls.json")
WORK = os.path.join(HERE, "_equiv_work")

CONTROLS = [
    {"name": "same function, renamed", "gold": "mac.v", "gold_top": "mac",
     "gate": "mac_alt.v", "gate_top": "mac_alt", "expect": True,
     "why": "the positive control. A gate that rejects an identical circuit is "
            "not strict, it is broken, and it would reject every correct result"},
    {"name": "smaller and different", "gold": "mac.v", "gold_top": "mac",
     "gate": "mac_wrong.v", "gate_top": "mac_small", "expect": False,
     "why": "the negative control: 152 cells smaller and wrong. This is the shape "
            "of every unproven area win"},
]


def measure(timeout=250):
    rows = []
    for c in CONTROLS:
        gold = os.path.join(RTL, c["gold"])
        gate = os.path.join(RTL, c["gate"])
        base = synth.run_synth(gold, c["gold_top"], optimize.BASELINE,
                               os.path.join(WORK, c["gold_top"], "base"),
                               timeout=timeout)
        got = synth.run_synth(gate, c["gate_top"], optimize.BASELINE,
                              os.path.join(WORK, c["gate_top"], "base"),
                              timeout=timeout)
        eq, detail = synth.prove_equivalent(gold, gate, c["gold_top"],
                                           c["gate_top"],
                                           os.path.join(WORK, c["gate_top"], "eq"),
                                           timeout=timeout)
        rows.append(dict(c, proven=eq, gold_cells=(base.metric.cells if base.metric else None),
                         gate_cells=(got.metric.cells if got.metric else None),
                         detail=detail.splitlines()[0][:120]))
    return rows


def main(argv=None):
    p = argparse.ArgumentParser(prog="run_equiv_controls.py", description=__doc__)
    p.add_argument("--replay", action="store_true")
    p.add_argument("--record", action="store_true")
    args = p.parse_args(argv)

    if args.replay:
        if not os.path.exists(RECORD):
            raise SystemExit("no record at %s" % RECORD)
        rows = json.load(open(RECORD, encoding="utf-8"))["controls"]
    else:
        rows = measure()
        if args.record:
            os.makedirs(os.path.dirname(RECORD), exist_ok=True)
            json.dump({"controls": rows}, open(RECORD, "w", encoding="utf-8"),
                      indent=2)

    print("%-24s %-10s %-8s %8s %8s  %s"
          % ("control", "expected", "proven", "gold", "gate", "cells"))
    print("-" * 78)
    bad = []
    for r in rows:
        dc = ("-" if r.get("gate_cells") is None or r.get("gold_cells") is None
              else "%+d" % (r["gate_cells"] - r["gold_cells"]))
        print("%-24s %-10s %-8s %8s %8s  %s"
              % (r["name"], r["expect"], r["proven"],
                 r.get("gold_cells"), r.get("gate_cells"), dc))
        if r["proven"] != r["expect"]:
            bad.append("%s: expected proven=%s, got %s -- %s"
                       % (r["name"], r["expect"], r["proven"], r.get("detail", "")))
    print("")
    for r in rows:
        print("%-24s %s" % (r["name"], r["why"]))
    smaller = next((r for r in rows
                    if r.get("gold_cells") and r.get("gate_cells")
                    and r["gate_cells"] < r["gold_cells"] and not r["expect"]), None)
    if smaller:
        print("")
        print("note: the rejected circuit is %d cells against %d -- smaller, and "
              "wrong. Without the gate, the search's own best result would have been "
              "this one."
              % (smaller["gate_cells"], smaller["gold_cells"]))
    print("")
    if bad:
        print("FAIL")
        for b in bad:
            print("  " + b)
        return 2
    print("PASS -- %d/%d controls matched" % (len(rows), len(CONTROLS)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
