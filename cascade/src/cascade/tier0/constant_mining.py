"""Tier 0b: constant mining.

Collects every integer literal a method's bytecode pushes, adds via
`iinc`, or implicitly compares against via an int `ifz`. The result is the constant dictionary `K`,
forwarded to parametrize the interval tier's widening thresholds (`∇K`)
and to seed the fuzzing tier's mutator.

Also collects string literals separately (`extract_string_constants`):
these have no role in `∇K` (the interval domain is numeric only), but are
exactly the kind of "value to use in a fuzzer" that seeds Tier 2's mutator
- e.g. mining "hello" from `assert greeting.equals("hello")` so a fuzzer
isn't left guessing a String parameter by random mutation.
"""

import sys
from collections.abc import Iterable

import jpamb
import jvm

STRING_TYPE = jvm.Object(jvm.ClassName("java.lang.String"))


def extract_constants(opcodes: Iterable[jvm.Opcode]) -> set[int]:
    """The set K: every integer constant occurring in `opcodes`."""
    constants: set[int] = set()

    for op in opcodes:
        match op:
            case jvm.Push(type=jvm.Int(), value=int() as value):
                constants.add(value)
            case jvm.Incr(amount=amount):
                constants.add(amount)
            case jvm.Ifz(condition=jvm.CmpOpr.Eq | jvm.CmpOpr.Ne | jvm.CmpOpr.Lt | jvm.CmpOpr.Ge | jvm.CmpOpr.Gt | jvm.CmpOpr.Le):
                constants.add(0)

    return constants


def extract_string_constants(opcodes: Iterable[jvm.Opcode]) -> set[str]:
    """Every string literal occurring literally in `opcodes` (fuzzer seeds only)."""
    constants: set[str] = set()

    for op in opcodes:
        match op:
            case jvm.Push(type=t, value=str() as value) if t == STRING_TYPE:
                constants.add(value)

    return constants


def main():
    methodid = jpamb.getmethodid(
        "tier0-constants", "0.1", "Group 21", ["syntactic", "python"], for_science=True
    )
    suite, eff = jpamb.setup()

    opcodes = list(suite.method_opcodes(methodid, eff=eff))
    constants = extract_constants(opcodes)
    strings = extract_string_constants(opcodes)
    print(f"mined constants K = {sorted(constants)}", file=sys.stderr)
    print(f"mined strings = {sorted(strings)}", file=sys.stderr)

    for query in jpamb.QUERIES:
        print(f"{query};skip")


if __name__ == "__main__":
    main()
