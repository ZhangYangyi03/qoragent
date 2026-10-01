# qoragent

Search synthesis passes. Keep a candidate only when the netlist got smaller AND
the function was proven identical.

Small, self-contained counterpart to
[agentic-eda](https://github.com/ZhangYangyi03/agentic-eda), which is the larger
version of this idea (13 strategies x 11 benchmarks, abc cec for combinational
proof, yosys equiv_induct for sequential, all the way to GDSII, plus a measured
self-test of the verifier itself). This repo exists because the core claim fits
in one file and one command: the equivalence gate, why it has to be
`equiv_opt -assert`, and the two traps -- `yosys -q` swallowing the `stat` block
this metric comes from, and `abc -g` rejecting `NOT`. If you want the result,
read agentic-eda. If you want to see the gate in 40 lines, read `synth.py` here.

## Why the gate, and not a heuristic

Synthesis optimisation has one failure mode that matters: a pass makes the
netlist smaller by making it different. Constant-folding an operand that was not
actually constant, retiming a flop across a boundary, sharing an operator whose
two uses are not actually exclusive -- all of these win on area and lose on
correctness. A tool that reports "42% fewer cells" and cannot answer "still the
same circuit?" is not optimising, it is breaking things quietly.

Equivalence is decidable, so it is decided. Every candidate is run through
yosys two ways:

    equiv_opt -assert <passes>      in-place passes, inside the search
    equiv_make / equiv_simple / equiv_status -assert
                                    two saved netlists, for regressions and review

`-assert` matters: without it yosys exits 0 after failing to prove equivalence,
and the shell return code -- the only thing a script reads -- would say the
candidate was fine. Verified in both directions on this host:

    same function   y = a + b      vs  y = b + a      -> Equivalence successfully proven!
    different       y = a + b      vs  y = a + b + 1  -> Found 5 unproven $equiv cells, ERROR

## Measured result

`bench/rtl/mac.v` -- a 16-bit signed multiply-accumulate, the smallest design
where synthesis choices visibly move the number:

    baseline   2190 cells   1.26s     (proc / opt / memory / techmap / opt)
    best        674 cells   2.92s     (-69.2%)
    kept       abc-lut6

    candidate              verdict                    cells
    abc-lut6               KEPT                       674
    abc-lut4               REJECTED_NOT_SMALLER       962
    abc-area               REJECTED_NOT_SMALLER      2033
    wreduce                REJECTED_NOT_SMALLER      2190
    opt-full               REJECTED_NOT_SMALLER      2190
    share                  REJECTED_NOT_SMALLER      2190
    retime                 REJECTED_NOT_SMALLER       674
    dfflegalize            REJECTED_NOT_SMALLER      2190

Seven of eight candidates were rejected. That is the honest shape of this
problem: most plausible optimisations do nothing on a given design, and the
value is in knowing which, quickly, with a decision procedure rather than an
opinion.

## The gate is tested in the direction that fails quietly

Handing the gate a broken circuit and watching it say no is the easy half. It is
also the half that fails loudly. The half that fails QUIETLY is the other one: a
gate that answers NO to a correct circuit looks strict, not broken, and it turns
the search into a program that can never keep anything. So both directions are
measured, and both are checked in as RTL:

    control                  expected   proven       gold     gate   cells
    same function, renamed   True       True         2190     2190      +0
    smaller and different    False      False        2190     2038    -152

`mac_alt.v` is the same multiply-accumulate with a different module name, and it
must be proven. `mac_wrong.v` is the same unit with `+ c` dropped: 152 cells
smaller, and wrong. Without the gate the search's own best result would have been
that second one.

The positive control is not ceremony. It found a real defect. With `equiv_simple`
alone, the identical renamed circuit came back with 97 unproven cells -- the gate
said NO to a circuit that IS the circuit:

    equiv_simple alone                 97 unproven -> "not equivalent"   WRONG
    equiv_simple + equiv_induct         0 unproven -> proven              right

An accumulator's state is only reachable by induction; `equiv_simple` stops at the
combinational cone. That is fixed, and it was only visible because a control asked
the gate for a yes.

Two smaller things the same exercise turned up:

  * two files that define the SAME module name are not a comparison -- yosys keeps
    one of them, `equiv_make` has nothing to compare, and the run returns no
    verdict at all. The message now says that instead of "no verdict produced".
  * a candidate whose metric could not be read has been shown to be UNMEASURED,
    not shown to be larger. `dfflegalize` exits cleanly and prints no stat block;
    reporting that as REJECTED_NOT_SMALLER claims a comparison that never
    happened. It is FAILED now.

    python bench/run_equiv_controls.py --replay    the record, no yosys needed

## The two traps this repo exists to document

1. `yosys -q` suppresses the `stat` block. The metric comes from `stat`, so a
   quiet run looks like a 0-cell design -- a 100% improvement that is really a
   failed measurement. This code never runs `-q` on a synthesis pass and treats
   a log without a stat block as a failed run, not a free win.

2. `abc -g` takes a comma-separated gate list but does not accept `NOT`
   (`Unsupported gate type: NOT`), and quoting the list is also wrong. Measured,
   not guessed; it is in the candidate table with the correct spelling.

## Install

    pip install -e .

Synthesis side (WSL or Linux):

    apt-get install -y yosys

## Use

    python -m qoragent doctor
    python -m qoragent search --rtl bench/rtl/mac.v --top mac \
        --workdir /tmp/qorsearch --json /tmp/qor.json
    python -m qoragent equiv --gold gold.v --gate gate.v \
        --gold-top gold --gate-top gate --workdir /tmp/eq

`search` exits 0 when it kept at least one proven-equivalent win, 2 when it kept
nothing. `equiv` exits 0 only on a proof.

## Layout

    qoragent/synth.py      run yosys, parse the metric, prove equivalence
    qoragent/optimize.py   the candidate table, the greedy search, the ledger
    bench/rtl/mac.v        the design under search
    bench/rtl/mac_alt.v    the positive control: same function, renamed
    bench/rtl/mac_wrong.v  the negative control: smaller, and wrong

## Honest limits

- The search is greedy and single-pass: it tries each candidate once against the
  best-so-far and never composes two losing halves into a winning whole.
- "Cells" is a proxy for area, and it is a fair one only within one library. A
  real area number needs a target liberty file and `abc -liberty`; `stat -tech
  cmos` and raw cell counts are what a library-free flow can honestly report.
  Timing is not measured at all -- no STA is in this flow -- so a smaller
  netlist is not claimed to be a faster one.
- Equivalence here is combinational-plus-flop-level over the same module
  boundary, and it needs BOTH `equiv_simple` and `equiv_induct` -- measured, the
  first alone rejects an identical renamed circuit. Buses wider than the mac's,
  memories, and multi-clock retiming are untested. Retiming across a hierarchy boundary, or a pass that changes the
  clock structure, is out of scope and would need `equiv_opt -multiclock`.

## License

Apache-2.0.


## Where this sits in the chain

This is one of four tools, and `autoforge` drives them. The sibling that joins
them is [eda-spine](https://github.com/ZhangYangyi03/eda-spine), and the question
it exists to ask is the one this repo's gate cannot:

    equivalence is one property. Does the kept netlist still satisfy the
    properties that were proved of the RTL?

Equivalence survives that question. So does area, for a counter: 10 cells into 8
in 0.6 s, and the netlist proves the property `"advances by exactly one"` just
as the RTL did. What does not survive is everything the property set never
mentioned -- which is why the other two tools are in the same chain.
