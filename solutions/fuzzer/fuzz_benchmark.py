"""Compare what the fuzzer finds with the errors the answer sheet lists."""

import sys
import time
from pathlib import Path

from fuzzer import fuzz
from mutators import Dictionary

import jpamb
from jpamb.case import Case

BUDGET = int(sys.argv[1]) if len(sys.argv) > 1 else 1000
ERRORS = {"divide by zero", "assertion error", "out of bounds", "null pointer"}

suite, eff = jpamb.setup()
bc = jpamb.Bytecode(suite, eff, {})
lines = Path("target/stats/cases.txt").read_text().splitlines()
cases = [Case.decode(line) for line in lines if line.strip()]


def class_constants(classname) -> Dictionary:
    """A throwaway stand-in for Tier 0: every int and string constant in the class."""
    ints, strings = set(), set()
    for method in suite.findclass(classname, eff=eff)["methods"]:
        for op in (method.get("code") or {}).get("bytecode", []):
            value = op["value"] if op["opr"] == "push" else None
            if value is not None:
                if value["type"] == "integer":
                    ints.add(value["value"])
                elif value["type"] == "string":
                    strings.add(value["value"])
    return Dictionary(tuple(sorted(ints)), tuple(sorted(strings)))


expected_total = found_with_k = found_without_k = 0
started = time.perf_counter()
for methodid, method_cases in Case.by_entry(cases):
    expected = {c.result for c in method_cases} & ERRORS
    if not expected:
        continue
    k = class_constants(methodid.classname)
    with_k = expected & set(fuzz(bc, methodid, BUDGET, 0, k).witnesses)
    without_k = expected & set(fuzz(bc, methodid, BUDGET, 0).witnesses)
    expected_total += len(expected)
    found_with_k += len(with_k)
    found_without_k += len(without_k)
    missed = "" if with_k == expected else "  <-- missed: " + ", ".join(sorted(expected - with_k))
    print(f"{methodid.extension.name:28} expected {len(expected)}  "
          f"with K {len(with_k)}  without K {len(without_k)}{missed}")

print(f"\nbudget {BUDGET}: found {found_with_k}/{expected_total} with K, "
      f"{found_without_k}/{expected_total} without K, in {time.perf_counter() - started:.0f}s")