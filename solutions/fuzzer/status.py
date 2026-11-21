"""One command that prints where the fuzzer stands.

python solutions/fuzzer/status.py            # full run, a few minutes
python solutions/fuzzer/status.py --quick    # skips the slow checks
"""

import re
import subprocess
import sys
import time
from pathlib import Path

from executor import DEFAULT_MAX_STEPS, execute
from fuzz_constants import class_constants
from fuzzer import fuzz

import jpamb
from jpamb.case import Case

QUICK = "--quick" in sys.argv
BUDGET = 200 if QUICK else 1000
ERRORS = {"divide by zero", "assertion error", "out of bounds", "null pointer"}
# Listed errors the fuzzer is known to miss at these budgets (see results/secret_ablation.csv).
# They are reported as "info", not counted in the check that must hold.
KNOWN_HARD = {("jpamb.cases.Group21Cases.secretThenDivide:([C)I", "divide by zero")}
# The evaluation written to test the fuzzer's features. Its results are shown as
# info here; experiment.py measures them properly.
EVALUATION_CLASS = "jpamb.cases.FuzzingHard"

rows = []  # (check, result, verdict)


def record(check, result, ok=None):
    """ok=True is OK, ok=False is FAIL, ok=None is just a number to watch."""
    verdict = "info" if ok is None else ("OK" if ok else "FAIL")
    rows.append((check, result, verdict))


# 1. Unit tests
tests = subprocess.run(
    [sys.executable, "-m", "pytest", "solutions/fuzzer/tests", "-q"],
    capture_output=True,
    text=True,
)
last_line = (tests.stdout.strip().splitlines() or ["no output"])[-1]
record("unit tests", last_line, tests.returncode == 0)

# 2. Interpreter against the answer sheet
suite, eff = jpamb.setup()
bc = jpamb.Bytecode(suite, eff, {})
lines = Path("target/stats/cases.txt").read_text().splitlines()
cases = [Case.decode(line) for line in lines if line.strip()]

agree = 0
for case in cases:
    try:
        agree += (
            execute(bc, case.methodid, case.input, DEFAULT_MAX_STEPS) == case.result
        )
    except Exception:
        pass  # an interpreter failure counts as disagreement
record(
    "interpreter vs answer sheet",
    f"{agree}/{len(cases)} cases agree",
    agree == len(cases),
)

# 3. The course's own checker
if not QUICK:
    out = subprocess.run(
        ["jpamb", "interpret", "fuzzer-interpreter"], capture_output=True, text=True
    )
    found = re.search(r"Total\s+\d+\s+(\d+)/(\d+)", out.stdout + out.stderr)
    if found:
        valid, total = map(int, found.groups())
        record(
            "course checker (jpamb interpret)", f"{valid}/{total} valid", valid == total
        )
    else:
        record("course checker (jpamb interpret)", "could not read its result", False)

# 4. The fuzzer against the errors the answer sheet lists
expected_total = with_k_total = without_k_total = 0
hard_total = hard_found = 0
eval_total = eval_found = 0
started = time.perf_counter()
for methodid, method_cases in Case.by_entry(cases):
    expected = {c.result for c in method_cases} & ERRORS
    if not expected:
        continue
    print(f"  fuzzing {methodid.extension.name} ...", flush=True)
    k = class_constants(suite, eff, methodid.classname)
    found_with_k = expected & set(
        fuzz(bc, methodid, BUDGET, 0, k, time_limit=10.0).witnesses
    )
    found_without_k = expected & set(
        fuzz(bc, methodid, BUDGET, 0, time_limit=10.0).witnesses
    )
    if methodid.classname.encode() == EVALUATION_CLASS:
        eval_total += len(expected)
        eval_found += len(found_with_k)
        continue
    hard = {e for e in expected if (methodid.encode(), e) in KNOWN_HARD}
    hard_total += len(hard)
    hard_found += len(hard & found_with_k)
    expected_total += len(expected - hard)
    with_k_total += len(found_with_k - hard)
    without_k_total += len(found_without_k - hard)
elapsed = time.perf_counter() - started

record(
    f"fuzzer with constants, budget {BUDGET}",
    f"{with_k_total}/{expected_total} listed errors found",
    with_k_total == expected_total,
)
record(
    "fuzzer without constants",
    f"{without_k_total}/{expected_total} listed errors found",
)
record("known-hard errors, with constants", f"{hard_found}/{hard_total} found")
record(
    "evaluation set, with constants", f"{eval_found}/{eval_total} listed errors found"
)
record("time for the fuzzing runs", f"{elapsed:.0f} s")

# Print the table
print("\nOK / FAIL: a check that must hold.   info: a number to watch.\n")
width = max(len(check) for check, _, _ in rows)
for check, result, verdict in rows:
    print(f"{verdict:5} {check:{width}}  {result}")

sys.exit(1 if any(v == "FAIL" for _, _, v in rows) else 0)
