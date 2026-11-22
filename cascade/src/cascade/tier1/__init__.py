"""Tier 1: unbounded interval analysis.

    from cascade.tier1 import analyse_method

    result = analyse_method("jpamb.cases.Simple.divideByN:(I)I", constants=K)
    result.verdicts     {"divide by zero": "maybe", "null pointer": "no", ...}
    result.alarms       where each "maybe" error can happen, with the intervals there

The modules:
    lattice.py    the interfaces (Poset, Lattice, Abstraction) and law checkers
    interval.py   the domain: Interval for ints, Ref for arrays
    analysis.py   the abstract interpreter, the fixed point, analyse_method
"""

from .analysis import Alarm, Result, analyse_method
from .interval import INT_MAX, INT_MIN, Branch, Interval, IntervalSplit, Ref
from .lattice import Abstraction, Lattice, Poset, is_galoi, is_lattice, is_poset
