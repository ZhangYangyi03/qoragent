"""CLI. The verdicts are the output; nothing here re-states them in prose."""

import argparse
import json
import os
import sys

from . import optimize, synth


def cmd_doctor(args):
    ok, ver = synth.toolchain_check()
    print("qoragent %s" % __import__("qoragent").__version__)
    print("synthesis   : %s" % ("yes -- " + ver if ok else "NO"))
    return 0 if ok else 1


def cmd_search(args):
    res = optimize.search(args.rtl, args.top, args.workdir,
                          timeout=args.timeout)
    print(optimize.report(res))
    if args.json:
        json.dump(res.to_dict(), open(args.json, "w", encoding="utf-8"), indent=2)
        print("\nwrote %s" % args.json)
    print("\nnetlist: %s" % res.netlist_path)
    return 0 if res.kept else 2


def cmd_equiv(args):
    eq, log = synth.prove_equivalent(args.gold, args.gate, args.gold_top,
                                     args.gate_top, args.workdir,
                                     timeout=args.timeout)
    print("equivalent: %s" % eq)
    if not eq:
        print(log[-1500:])
    return 0 if eq else 2


def main(argv=None):
    p = argparse.ArgumentParser(prog="qoragent", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("doctor"); d.set_defaults(func=cmd_doctor)

    s = sub.add_parser("search", help="try passes, keep only equivalent wins")
    s.add_argument("--rtl", required=True)
    s.add_argument("--top", required=True)
    s.add_argument("--workdir", required=True)
    s.add_argument("--timeout", type=int, default=300)
    s.add_argument("--json", default=None)
    s.set_defaults(func=cmd_search)

    e = sub.add_parser("equiv", help="prove two netlists compute the same function")
    e.add_argument("--gold", required=True)
    e.add_argument("--gate", required=True)
    e.add_argument("--gold-top", required=True)
    e.add_argument("--gate-top", required=True)
    e.add_argument("--workdir", required=True)
    e.add_argument("--timeout", type=int, default=300)
    e.set_defaults(func=cmd_equiv)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
