"""Show the witnesses the fuzzer finds for one method."""

import sys

from fuzz_constants import class_constants
from fuzzer import fuzz

import jpamb
import jvm

methodid = jvm.AbsMethodID.decode(sys.argv[1])
suite, eff = jpamb.setup()
bc = jpamb.Bytecode(suite, eff, {})
result = fuzz(bc, methodid, 1000, 0, class_constants(suite, eff, methodid.classname), time_limit=3.0)

for outcome, witness in result.witnesses.items():
    print(f"{outcome:16} {witness.input.encode()}   ({witness.steps} steps)")
print(f"{result.executions} executions, {len(result.failures)} kinds of interpreter failure")