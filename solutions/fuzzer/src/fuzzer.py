"""Coverage-guided fuzzing of one method.

Depends only on jpamb, jvm and own executor and mutators modules."""

import random
import time
from collections import Counter
from dataclasses import dataclass

from executor import DEFAULT_MAX_STEPS, run
from mutators import Dictionary, initial_input, mutate_input

import jpamb
import jvm

ATTEMPT_FACTOR = 20     # Give up after budget * ATTEMPT_FACTOR attempts

@dataclass(frozen=True)
class Witness:
    """An input that makes the method end in an error."""

    outcome: str
    input: jpamb.Input
    steps: int

@dataclass(frozen=True)
class FuzzResult:
    witnesses: dict[str, Witness]   # The first witness for each error outcome
    coverage: set                   # Every instruction (PC) any run executed
    observed: list                  # (input, outcome) for every run completed
    executions: int                 # No. of runs actually executed
    corpus_size: int
    failures: Counter               # Interpreter failures: message -> count

def fuzz(
        bc,
        methodid: jvm.AbsMethodID,
        budget: int,
        seed: int,
        dictionary: Dictionary = Dictionary(),
        focus: set | None = None,
        max_steps: int = DEFAULT_MAX_STEPS,
        time_limit: float | None = None,
) -> FuzzResult:
    rng = random.Random(seed)
    deadline = None if time_limit is None else time.perf_counter() + time_limit
    start = initial_input(methodid)
    corpus = []                         # Inputs we mutate from
    tried = set()                       # Every input we have run. Never run twice
    seen = set()                        # Instructions that count as progress so far
    covered = set()                     # Any instruction any run executed
    witnesses = {}
    observed = []
    failures = Counter()
    executions = 0

    def candidates():
        yield start
        while True:
            yield mutate_input(rng, rng.choice(corpus or [start]), dictionary)

    attempts = 0
    for candidate in candidates():
        if executions >= budget or attempts >= budget * ATTEMPT_FACTOR:
            break
        if deadline is not None and time.perf_counter() > deadline:
            break
        attempts += 1
        if candidate in tried:
            continue
        tried.add(candidate)

        result = run(bc, methodid, candidate, max_steps)
        executions += 1

        if result.failure is not None:  # Interpreter broke, not Java
            failures[result.failure] += 1
            continue

        observed.append((candidate, result.outcome))
        covered |= result.coverage

        if result.outcome not in ("ok", "*") and result.outcome not in witnesses:
            witnesses[result.outcome] = Witness(result.outcome, candidate, result.steps)

        progress = result.coverage if focus is None else result.coverage & focus
        if progress - seen:         # Reached something new
            seen |= progress
            corpus.append(candidate)

    return FuzzResult(witnesses, covered, observed, executions, len(corpus), failures)