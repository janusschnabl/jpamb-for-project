"""Tests for Tier 2 on top of the cascade.

Run from the repository root:
    uv run --with-editable cascade --with pytest python -m pytest cascade/tests/test_tier2.py -q
"""

from pathlib import Path

import pytest
from cascade.pipeline import Cascade
from cascade.tier2 import run_tier2

ROOT = Path(__file__).parents[2]


def ground_truth() -> dict[str, set[str]]:
    """The outcomes each method really has, from its @Case annotations."""
    truth: dict[str, set[str]] = {}
    for line in (
        (ROOT / "target" / "stats" / "cases.txt")
        .read_text(encoding="utf-8")
        .splitlines()
    ):
        if "->" in line:
            truth.setdefault(line.split()[0], set()).add(
                line.rsplit("->", 1)[1].strip()
            )
    return truth


TRUTH = ground_truth()
# Real Java does these, nut the @Case annotations do not list them.
UNLISTED = {
    # (o, MIN_VALUE): -MIN_VALUE overflows to MIN_VALUE, so x >= y and dst / 0
    ("jpamb.cases.Dependent.normalizedDistance:(II)I", "divide by zero"),
}


@pytest.fixture(scope="module")
def cascade():
    return Cascade()


def tier2_for(cascade, methodid, **kwargs):
    result = cascade.run(methodid)
    return result, run_tier2(cascade.bc, result, **kwargs)


@pytest.mark.parametrize("methodid", sorted(TRUTH))
def test_yes_is_real_and_no_is_not_wrong(cascade, methodid):
    """Soundness: a "yes" must be a real outcome, a "no" must never be one."""
    _, tier2 = tier2_for(cascade, methodid, budget=200, time_limit=2.0)
    for query, verdict in tier2.verdicts.items():
        if verdict.answer == "yes":
            ok = query in TRUTH[methodid] or (methodid, query) in UNLISTED
            assert ok, f"claimed {query} happens, it does not"
        else:
            assert query not in TRUTH[methodid], (
                f"claimed {query} impossible, it happens"
            )


def test_tier2_only_touches_undecided_queries(cascade):
    result, tier2 = tier2_for(cascade, "jpamb.cases.Simple.divideByN:(I)I")
    assert set(tier2.verdicts) <= set(result.undecided())


def test_tier2_finds_what_the_static_tiers_cannot(cascade):
    # return 1 / n;  Tiers 0 and 1 cannot say no, the fuzzer finds n == 0
    _, tier2 = tier2_for(cascade, "jpamb.cases.Simple.divideByN:(I)I")
    assert tier2.verdicts["divide by zero"].answer == "yes"
    assert tier2.witnesses["divide by zero"]


def test_mined_strings_reach_the_fuzzer(cascade):
    # assert !s.equals("open sesame");  needs the literal from Tier 0
    _, tier2 = tier2_for(
        cascade, "jpamb.cases.FuzzingHard.secretPhrase:(Ljava/lang/String;)V"
    )
    assert tier2.verdicts["assertion error"].answer == "yes"


def test_alarm_pcs_are_comparable_with_coverage(cascade):
    # The focus only works if Tier 1's PCs are the same objects the interpreter reports.
    result, tier2 = tier2_for(cascade, "jpamb.cases.Simple.divideByN:(I)I")
    (alarm,) = result.tier1.unproven("divide by zero")
    assert alarm.pc in tier2.fuzz.coverage
