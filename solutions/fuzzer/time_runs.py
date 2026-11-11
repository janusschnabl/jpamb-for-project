import time
from pathlib import Path

from executor import run

import jpamb
from jpamb.case import Case

suite, eff = jpamb.setup()
bc = jpamb.Bytecode(suite, eff, {})
lines = Path("target/stats/cases.txt").read_text().splitlines()
cases = [Case.decode(line) for line in lines if line.strip()]

for limit in (1_000, 10_000, 100_000):
    start = time.perf_counter()
    runs = steps = 0
    for _ in range(3):
        for case in cases:
            r = run(bc, case.methodid, case.input, max_steps=limit)
            runs += 1
            steps += r.steps
    secs = time.perf_counter() - start
    print(f"limit {limit:>7}: {runs / secs:8.0f} runs/s, {steps / secs:10.0f} steps/s")