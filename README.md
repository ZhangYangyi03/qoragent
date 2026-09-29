# qoragent

Search synthesis passes. Keep a candidate only when the netlist got smaller AND
the function was proven identical.

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

## Honest limits

- The search is greedy and single-pass: it tries each candidate once against the
  best-so-far and never composes two losing halves into a winning whole.
- "Cells" is a proxy for area, and it is a fair one only within one library. A
  real area number needs a target liberty file and `abc -liberty`; `stat -tech
  cmos` and raw cell counts are what a library-free flow can honestly report.
  Timing is not measured at all -- no STA is in this flow -- so a smaller
  netlist is not claimed to be a faster one.
- Equivalence here is combinational-plus-flop-level over the same module
  boundary. Retiming across a hierarchy boundary, or a pass that changes the
  clock structure, is out of scope and would need `equiv_opt -multiclock`.

## License

Apache-2.0.
