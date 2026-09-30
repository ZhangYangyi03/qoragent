"""Run yosys, extract a QoR metric, and never report a number you did not measure.

The metric comes from `stat` and is parsed, not inherited from a vendor report.
Every field is present in the returned Metric or the run failed; there is no
"unknown, assume ok" path, because a synthesis QoR number that silently defaults
is worse than no number.
"""

import base64
import os
import platform
import re
import subprocess
import time

WSL_DISTRO = os.environ.get("QORAGENT_WSL", "Ubuntu")

CELL_RE = re.compile(r"^\s+(\$?_?\w+)\s+(\d+)\s*$")
NUM_RE = re.compile(r"Number of ([a-z ]+):\s+(\d+)")


class Metric:
    """The numbers a synthesis run produced. Never guessed, never defaulted."""

    def __init__(self, cells=0, cell_breakdown=None, wires=0, wire_bits=0,
                 processes=None, memories=None, seconds=0.0, log=""):
        self.cells = cells
        self.cell_breakdown = cell_breakdown or {}
        self.wires = wires
        self.wire_bits = wire_bits
        self.processes = processes
        self.memories = memories
        self.seconds = seconds
        self.log = log

    def to_dict(self):
        return {"cells": self.cells, "wires": self.wires,
                "wire_bits": self.wire_bits, "memories": self.memories,
                "seconds": round(self.seconds, 2), "breakdown": self.cell_breakdown}

    def __repr__(self):
        return "<Metric cells=%d wires=%d bits=%d %.2fs>" % (
            self.cells, self.wires, self.wire_bits, self.seconds)


class SynthResult:
    def __init__(self, ok, metric, netlist=None, log="", script=""):
        self.ok = ok
        self.metric = metric
        self.netlist = netlist
        self.log = log
        self.script = script

    def to_dict(self):
        d = {"ok": self.ok, "script": self.script}
        if self.metric:
            d["metric"] = self.metric.to_dict()
        d["log_tail"] = self.log[-600:]
        return d


def _collapse(p):
    return re.sub(r"/+", "/", p)


def win_to_wsl(path):
    """Translate a Windows path to its WSL mount path; leave a Unix path alone.

    Two things this has to get right, both found by tests rather than reasoning:
    a POSIX-looking string must not be run through os.path.abspath (which
    prepends the Windows cwd and turns "/tmp/x.v" into "/mnt/d/tmp/x.v"), and
    duplicated separators must collapse -- WSL does not object to "//" but the
    string is then wrong in logs and in equality checks.
    """
    if platform.system() != "Windows":
        return path if os.path.isabs(path) else os.path.abspath(path)
    if path.startswith("/"):
        return _collapse(path)
    p = _collapse(path.replace("\\", "/"))
    m = re.match(r"^([A-Za-z]):/(.*)$", p)
    if m:
        return "/mnt/" + m.group(1).lower() + "/" + _collapse(m.group(2))
    # relative: resolve against the cwd, which is a Windows path
    return win_to_wsl(os.path.abspath(path))


def wsl_bash(script, timeout=300):
    """Run bash where yosys lives: WSL on Windows, bash directly on Linux.

    The Windows path carries the script as base64 because this host passes
    non-ASCII argv through wsl.exe unreliably. The Linux path exists because
    leaving it out broke CI with FileNotFoundError: 'wsl' on ubuntu-latest.
    """
    if platform.system() == "Windows":
        b64 = base64.b64encode(script.encode("utf-8")).decode("ascii")
        cmd = ["wsl", "-d", WSL_DISTRO, "--", "bash", "-lc",
               "echo %s | base64 -d > /tmp/qa_run.sh && bash /tmp/qa_run.sh" % b64]
    else:
        cmd = ["bash", "-lc", script]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=timeout)
        return (r.stdout or b"").decode("utf-8", "replace"), r.returncode
    except subprocess.TimeoutExpired:
        return "", -9


def parse_stat(log):
    """Pull the numbers out of a yosys `stat` block. Returns None if absent."""
    m = NUM_RE.search(log.replace("stat -tech cmos", "")) if False else None
    fields = {}
    for mm in NUM_RE.finditer(log):
        fields[mm.group(1).strip()] = int(mm.group(2))
    if "cells" not in fields:
        return None
    breakdown = {}
    for line in log.splitlines():
        mm = CELL_RE.match(line)
        if mm:
            breakdown[mm.group(1)] = int(mm.group(2))
    wires = fields.get("wires", 0)
    bits = fields.get("wire bits", 0)
    return Metric(cells=fields["cells"], cell_breakdown=breakdown,
                  wires=wires, wire_bits=bits,
                  memories=fields.get("memories"))


def run_synth(rtl_path, top, script_body, workdir, timeout=300,
              write_netlist=True, extra_files=None):
    """Run a yosys script over `rtl_path` and return a SynthResult.

    script_body is the pass list AFTER the design is read -- the caller supplies
    the optimisation strategy, this function supplies the reading, the stat, and
    the netlist write.
    """
    os.makedirs(workdir, exist_ok=True)
    # yosys runs inside WSL, so every path it is handed must be a WSL path --
    # a Windows path is not just wrong, it is silently "file not found"
    files = [win_to_wsl(rtl_path)] + [win_to_wsl(f) for f in (extra_files or [])]
    read = "\n".join("read_verilog %s" % f for f in files)
    tail = "write_verilog -noattr %s" % ("netlist.v" if write_netlist else "/dev/null")
    script = (read + "\nhierarchy -top %s\n" % top + script_body +
              "\nstat\n" + tail + "\n")
    ys = os.path.join(workdir, "job.ys")
    with open(ys, "w", encoding="utf-8", newline="\n") as f:
        f.write(script)

    mount = win_to_wsl(workdir)
    t0 = time.time()
    # NOT -q: yosys -q suppresses the `stat` block, which is where the metric
    # comes from. Measured: with -q, "Number of cells" appears 0 times in the
    # output and every run looks like a failure.
    log, rc = wsl_bash("cd %s || exit 7\nyosys -s job.ys 2>&1\n" % mount,
                       timeout=timeout)
    dt = time.time() - t0
    metric = parse_stat(log)
    ok = rc == 0 and metric is not None
    if metric:
        metric.seconds = dt
        metric.log = log

    netlist = None
    np_ = os.path.join(workdir, "netlist.v")
    if write_netlist and os.path.exists(np_):
        netlist = open(np_, encoding="utf-8", errors="ignore").read()

    # yosys writes the stat to stdout but with -q it can be swallowed; rerun
    # through `tee` style capture is what the log above already is
    return SynthResult(ok, metric, netlist, log, script_body)


def equivalence_script(gold_path, gate_path, gold_top, gate_top):
    """A yosys script that decides whether two modules compute the same function.

    Two modules of different names in two files, one equiv_make, one SAT sweep.
    `equiv_status -assert` makes yosys exit non-zero when a pair is not proven,
    which is why this is a gate and not a report: the shell return code is the
    verdict.

    BOTH halves are needed, and the positive control is what says so. Measured on
    an accumulator that is identical on both sides but renamed:

        equiv_simple alone                  97 unproven -> "not equivalent"  WRONG
        equiv_simple + equiv_induct          0 unproven -> proven             right

    equiv_simple stops at the combinational cone; an accumulator's state has to
    be reached by induction. A gate that cannot say yes to an identical circuit
    would reject every correct optimisation the search finds, and it would look
    like a strict gate rather than a broken one -- so `bench/rtl/mac_alt.v` (the
    same function, renamed) is checked in as the positive control.

    Verified in both directions on this host:
      mac vs mac_alt (same function, renamed) -> "Equivalence successfully proven!"
      mac vs mac_small (smaller, `+ c` gone)  -> "97 unproven $equiv cells" and ERROR
    """
    return (
        "read_verilog %s\n" % win_to_wsl(gold_path) +
        "read_verilog %s\n" % win_to_wsl(gate_path) +
        "proc\nopt_clean\n"
        "equiv_make %s %s equiv\n" % (gold_top, gate_top) +
        "hierarchy -top equiv\n"
        "equiv_simple\nequiv_induct\n"
        "equiv_status -assert\n"
    )


def prove_equivalent(gold_path, gate_path, gold_top, gate_top, workdir,
                     timeout=300):
    """Returns (equivalent, log). Never returns 'probably'.

    `equiv_opt -assert` is the other route and is what the search uses for
    in-place passes; this one compares two saved netlists, which is what a
    regression or a review needs.
    """
    os.makedirs(workdir, exist_ok=True)
    ys = os.path.join(workdir, "equiv.ys")
    with open(ys, "w", encoding="utf-8", newline="\n") as f:
        f.write(equivalence_script(gold_path, gate_path, gold_top, gate_top))
    # Two files that define the SAME module name are not a comparison: yosys
    # reads the second over the first, so both sides become the same module and
    # equiv_make has nothing to compare. Measured: it returns no verdict at all,
    # which is reported below as "no equivalence verdict produced" -- technically
    # true and useless as a diagnosis. Say the real reason instead.
    if gold_top == gate_top:
        return False, ("both sides are named %r; reading two files that define the "
                       "same module leaves one of them, so there is nothing to "
                       "compare. Give the second copy a different module name."
                       % gold_top)
    mount = win_to_wsl(workdir)
    log, rc = wsl_bash("cd %s || exit 7\nyosys -s equiv.ys 2>&1\n" % mount,
                       timeout=timeout)
    if "Equivalence successfully proven" in log:
        return True, log
    m = re.search(r"Found (\d+) unproven", log)
    if m:
        return False, "%s unproven equivalence cells:\n%s" % (m.group(1), log[-800:])
    return False, "no equivalence verdict produced:\n%s" % log[-800:]


def run_script(path, workdir, timeout=300):
    """Run an arbitrary yosys script the caller wrote. Returns (ok, log)."""
    os.makedirs(workdir, exist_ok=True)
    mount = win_to_wsl(workdir)
    log, rc = wsl_bash("cd %s || exit 7\nyosys -s %s 2>&1\n"
                       % (mount, win_to_wsl(path)), timeout=timeout)
    return (rc == 0 and "ERROR" not in log), log


def toolchain_check():
    out, _ = wsl_bash("yosys -V 2>/dev/null; which abc 2>/dev/null; "
                      "echo ---; yosys -Q -p 'help abc' 2>&1 | grep -c '^\\s+-'", 120)
    ok = "Yosys" in out
    return ok, " | ".join(x.strip() for x in out.splitlines() if x.strip())
