"""Tier 2 adapter: feeds the cascade's knowledge to the fuzzer, turns outcomes into answers."""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from fuzzer import FuzzResult, Witness, fuzz
from mutators import Dictionary

from cascade.tier0.constant_mining import extract_string_constants

if TYPE_CHECKING:  # only for type hints; importing pipeline here would be circular
    from cascade.pipeline import CascadeResult

BUDGET = 1000  # executions per method
TIME_LIMIT = 3.0  # seconds per method; check it against the harness timeout
SEED = 0


@dataclass
class Tier2Result:
    answers: dict[str, str]  # "yes" or "no", only for the queries Tier 2 decided
    witnesses: dict[str, Witness]  # the inputs that cause each error
    fuzz: FuzzResult | None  # None if there was nothing to fuzz
    focus: set | None  # the PCs the fuzzer was steered towards


def alarm_pcs(result: "CascadeResult", queries: list[str]) -> set | None:
    """Where Tier 1 could not prove the undecided errors safe, or None if it said nothing."""
    if result.tier1 is None or not result.tier1.analysed:
        return None
    pcs = {alarm.pc for alarm in result.tier1.alarms if alarm.error in queries}
    return pcs or None  # an empty focus would stop the corpus from ever growing


def run_tier2(
    bc,
    result: "CascadeResult",
    budget: int = BUDGET,
    seed: int = SEED,
    time_limit: float | None = TIME_LIMIT,
) -> Tier2Result:
    queries = result.undecided()
    if not queries:
        return Tier2Result({}, {}, None, None)

    methodid = result.methodid
    strings = extract_string_constants(bc.getmethod(methodid).opcodes)
    dictionary = Dictionary(
        ints=tuple(sorted(result.constants)),
        strings=tuple(sorted(strings)),
    )
    focus = alarm_pcs(result, queries)
    fuzzed = fuzz(
        bc, methodid, budget, seed, dictionary, focus=focus, time_limit=time_limit
    )

    seen = {outcome for _, outcome in fuzzed.observed}
    parameterless = len(methodid.extension.params) == 0
    # With no parameters there is exactly one possible run, so a finished run
    # settles every query.
    complete = parameterless and "*" not in seen and bool(seen)

    answers: dict[str, str] = {}
    for query in queries:
        if query == "*":
            # A step-limit hit only suggests non-termination when there is one possible run.
            found = parameterless and "*" in seen
        else:
            found = query in seen
        if found:
            answers[query] = "yes"
        elif complete:
            answers[query] = "no"

    return Tier2Result(answers, fuzzed.witnesses, fuzzed, focus)
