from pathlib import Path

import jpamb
from jpamb.case import Case

from executor import run

suite, eff = jpamb.setup()
bc = jpamb.Bytecode(suite, eff, {})
lines = Path("target/stats/cases.txt").read_text().splitlines()
cases = [Case.decode(line) for line in lines if line.strip()]

rows = []
for case in cases:
    r = run(bc, case.methodid, case.input, max_steps=100_000)
    if r.outcome != "*":
        rows.append((r.steps, r.outcome, case.experiment.short()))

for steps, outcome, name in sorted(rows, reverse=True)[0:8]:
    print(f"{steps:7}   {outcome:15} {name}")