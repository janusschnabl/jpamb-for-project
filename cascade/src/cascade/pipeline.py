"""The cascade: cheap before expensive.

Every query (one JPAMB outcome for one method) goes through the tiers in
order, and stops at the first tier that can decide it:

    Tier 0  syntactic       "no"   no instruction that can cause it is reachable
            -> forwards the constants K
    Tier 1  intervals       "no"   no input can cause it (abstract interpretation)

Tiers 0 and 1 can only prove impossibility, so what is left is "undecided"
here.  Tiers 2 (fuzzing) and 3 (guards) will take it from there.

    from cascade.pipeline import Cascade

    cascade = Cascade()
    result = cascade.run("jpamb.cases.Simple.divideByN:(I)I")
    result.verdicts["divide by zero"]     Verdict(answer="undecided", tier=None)
    result.verdicts["null pointer"]       Verdict(answer="no", tier=0)
"""

import contextlib
import io
import sys
import time
from dataclasses import dataclass, field

import jpamb
import jvm
from cascade.tier0.constant_mining import extract_constants
from cascade.tier0.opcode_absence import ALL_OUTCOMES, Program
from cascade.tier0.opcode_absence import analyse as find_fault_sites
from cascade.tier1 import Result, analyse_method
from cascade.tier2 import Tier2Result, run_tier2


@dataclass(frozen=True)
class Verdict:
    answer: str
    tier: int | None = None


@dataclass
class CascadeResult:
    methodid: jvm.AbsMethodID
    verdicts: dict[str, Verdict]
    constants: set[int]
    tier1: Result | None = None
    tier2: Tier2Result | None = None
    seconds: dict[int, float] = field(default_factory=dict)

    def undecided(self) -> list[str]:
        return [q for q, v in self.verdicts.items() if v.answer == "undecided"]


class Cascade:
    def __init__(self, suite: jpamb.Suite | None = None, eff=None):
        if suite is None:
            suite, eff = jpamb.setup()
        self.bc = jpamb.Bytecode(suite, eff, {})
        self.program = Program(suite, eff)

    def run(self, methodid: str | jvm.AbsMethodID, fuzz: bool = False) -> CascadeResult:
        if isinstance(methodid, str):
            methodid = jpamb.parse_methodid(methodid)
        verdicts = {q: Verdict("undecided") for q in jpamb.QUERIES}

        start = time.perf_counter()
        sites = find_fault_sites(self.program, methodid)
        for query in jpamb.QUERIES:
            if query in ALL_OUTCOMES and not sites[query]:
                verdicts[query] = Verdict("no", tier=0)
        constants = extract_constants(self.bc.getmethod(methodid).opcodes)
        result = CascadeResult(methodid, verdicts, constants)
        result.seconds[0] = time.perf_counter() - start

        # skip Tier 1 if Tier 0 already decided every error
        if any(q in ALL_OUTCOMES for q in result.undecided()):
            start = time.perf_counter()
            with contextlib.redirect_stderr(io.StringIO()):
                tier1 = analyse_method(methodid, self.bc, constants=constants)
            for query in result.undecided():
                if tier1.proven(query):
                    verdicts[query] = Verdict("no", tier=1)
            result.tier1 = tier1
            result.seconds[1] = time.perf_counter() - start

        if fuzz and result.undecided():
            start = time.perf_counter()
            tier2 = run_tier2(self.bc, result)
            for query, answer in tier2.answers.items():
                verdicts[query] = Verdict(answer, tier=2)
            result.tier2 = tier2
            result.seconds[2] = time.perf_counter() - start

        return result


def prediction(verdict: Verdict) -> str:
    """The word JPAMB sees. JPAMB scores each word by how often it was right,
    so weaker evidence gets its own word and cannot spoil a stronger one."""
    match verdict.answer, verdict.tier:
        case "no", 2:
            return "no-run"  # one finished run of a parameterless method
        case "no", _:
            return "no"
        case "yes", _:
            return "yes"
        case _:
            return "maybe"


def main():
    methodid = jpamb.getmethodid(
        "cascade",
        "0.1",
        "Group 21",
        ["syntactic", "static", "intervals", "python"],
        for_science=True,
    )
    result = Cascade().run(methodid, fuzz=True)

    for query in jpamb.QUERIES:
        verdict = result.verdicts[query]
        decided_by = "" if verdict.tier is None else f" (tier {verdict.tier})"
        print(f"{query}: {verdict.answer}{decided_by}", file=sys.stderr)
        print(f"{query};{prediction(verdict)}")


if __name__ == "__main__":
    main()
