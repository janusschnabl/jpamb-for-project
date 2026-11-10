"""Run the benchmark cases through the interpreter and report agreement."""

import collections
from pathlib import Path

from executor import execute

import jpamb
from jpamb.case import Case

suite, eff = jpamb.setup()
bc = jpamb.Bytecode(suite, eff, {})

lines = Path("target/stats/cases.txt").read_text().splitlines()
cases = [Case.decode(line) for line in lines if line.strip()]

tally = collections.defaultdict(collections.Counter)
for case in cases:
    klass = case.methodid.classname.name
    try:
        outcome = execute(bc, case.methodid, case.input)
    except NotImplementedError as e:
        tally[klass]["unsupported"] += 1
        tally[klass][f"  missing: {str(e)[:70]}"] += 1
        continue
    except Exception as e:
        tally[klass]["crashed"] += 1
        print(f"CRASH {case}: {type(e).__name__}: {e}")
        continue
    if outcome == case.result:
        tally[klass]["pass"] += 1
    else:
        tally[klass]["WRONG"] += 1
        print(f"WRONG {case}  got: {outcome}")

for klass, counter in sorted(tally.items()):
    print(f"\n{klass}")
    for key, n in counter.items():
        print(f"  {key}: {n}")