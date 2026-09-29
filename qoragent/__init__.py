"""qoragent -- QoR search over synthesis passes, gated by proven equivalence.

A smaller netlist is only an improvement if it is still the same circuit. Every
candidate this package keeps has been through `equiv_opt -assert`, which is a
decision procedure, not a review step.
"""

__version__ = "0.1.0"

from . import optimize, synth  # noqa: F401

__all__ = ["optimize", "synth"]
