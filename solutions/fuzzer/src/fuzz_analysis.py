"""Entry point for `jpamb analyse`: fuzz the method and report what was found."""

from fuzz_constants import class_constants
from fuzzer import fuzz

import jpamb

BUDGET = 1000        # executions per method
TIME_LIMIT = 3.0    # seconds per method; check it against the harness timeout
SEED = 0


def analyse():
    methodid = jpamb.getmethodid(
        "fuzzer-analysis",
        "1.0",
        "Group 21",
        ["dynamic", "python", "random", "coverage", "dictionary", "syntactic"],
        for_science=True,
    )
    suite, eff = jpamb.setup()
    bc = jpamb.Bytecode(suite, eff, {})

    dictionary = class_constants(suite, eff, methodid.classname)
    result = fuzz(bc, methodid, BUDGET, SEED, dictionary, time_limit=TIME_LIMIT)

    seen = {outcome for _, outcome in result.observed}
    parameterless = len(methodid.extension.params) == 0
    # With no parameters there is exactly one possible run, so a finished run
    # settles every query.
    complete = parameterless and "*" not in seen and bool(seen)

    for query in jpamb.QUERIES:
        if query == "*":
            # A step-limit hit is only evidence of non-termination when there is
            # a single possible run. With parameters it is usually just a big input.
            if parameterless and "*" in seen:
                answer = "timeout"
            else:
                answer = "no" if complete else "not-found"
        elif query in seen:
            answer = "found"
        else:
            answer = "no" if complete else "not-found"
        print(f"{query};{answer}")