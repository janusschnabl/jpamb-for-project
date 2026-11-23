"""Before/after check on secretThenDivide: in how many of th 10 seeds does the fuzzer find the bug, and after how many executions?"""

from fuzz_constants import class_constants
from fuzzer import fuzz
from mutators import Dictionary

import jpamb
import jvm

suite, eff = jpamb.setup()
bc = jpamb.Bytecode(suite, eff, {})
method = jvm.AbsMethodID.decode("jpamb.cases.Group21Cases.secretThenDivide:([C)I")
constants = class_constants(suite, eff, method.classname)

for label, dictionary in (
    ("with constants", constants),
    ("without constants", Dictionary()),
):
    first_hits = []
    for seed in range(10):
        result = fuzz(bc, method, 5000, seed, dictionary, time_limit=30)
        witness = result.witnesses.get("divide by zero")
        if witness is not None:
            first_hits.append(witness.execution)
    print(
        f"{label:18} found in {len(first_hits)}/10 seeds; "
        f"executions to first witness: {sorted(first_hits)}"
    )
