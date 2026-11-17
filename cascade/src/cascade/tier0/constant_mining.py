"""Tier 0b: constant mining.

Collects every integer literal a method's bytecode pushes or adds
via `iinc`. The constant dictionary `K`, forwarded to parametrize 
the interval tier's widening thresholds (`∇K`) and to seed the
fuzzing tier's mutator.
"""

import sys
from collections.abc import Iterable

import jpamb
import jvm


def extract_constants(opcodes: Iterable[jvm.Opcode]) -> set[int]:
    """The set K: every integer constant occurring literally in `opcodes`."""
    constants: set[int] = set()

    for op in opcodes:
        match op:
            case jvm.Push(type=jvm.Int(), value=int() as value):
                constants.add(value)
            case jvm.Incr(amount=amount):
                constants.add(amount)
            # case jvm.Ifz(condition=jvm.CmpOpr.Eq | jvm.CmpOpr.Ne | jvm.CmpOpr.Lt | jvm.CmpOpr.Ge | jvm.CmpOpr.Gt | jvm.CmpOpr.Le):
            #     constants.add(0)

    return constants


def main():
    methodid = jpamb.getmethodid(
        "tier0-constants", "0.1", "Group 21", ["syntactic", "python"], for_science=True
    )
    suite, eff = jpamb.setup()

    constants = extract_constants(suite.method_opcodes(methodid, eff=eff))
    print(f"mined constants K = {sorted(constants)}", file=sys.stderr)

    for query in jpamb.QUERIES:
        print(f"{query};skip")


if __name__ == "__main__":
    main()
