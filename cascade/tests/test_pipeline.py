"""Tests for the Tier 0 -> Tier 1 pipeline.

Run from the repository root:
    uv run --with-editable cascade --with pytest python -m pytest cascade/tests -q
"""

from pathlib import Path

import pytest

from cascade.pipeline import Cascade

ROOT = Path(__file__).parents[2]


def ground_truth() -> dict[str, set[str]]:
    """The outcomes each method really has, from its @Case annotations."""
    truth: dict[str, set[str]] = {}
    for line in (ROOT / "target" / "stats" / "cases.txt").read_text(encoding="utf-8").splitlines():
        if "->" in line:
            truth.setdefault(line.split()[0], set()).add(line.rsplit("->", 1)[1].strip())
    return truth


TRUTH = ground_truth()


@pytest.fixture(scope="module")
def cascade():
    return Cascade()


@pytest.mark.parametrize("methodid", sorted(TRUTH))
def test_never_says_no_to_a_real_outcome(cascade, methodid):
    """Soundness: a "no" from either tier must never be wrong."""
    result = cascade.run(methodid)
    wrong = {q for q in TRUTH[methodid] if result.verdicts[q].answer == "no"}
    assert not wrong, f"claimed impossible, but happens: {wrong}"


def test_tier0_decides_a_method_without_risky_instructions(cascade):
    # return a + b;   no division, no array, no assertion
    result = cascade.run("jpamb.cases.Simple.justAdd:(II)I")
    for query in ("divide by zero", "out of bounds", "assertion error", "null pointer"):
        assert result.verdicts[query].tier == 0
    assert result.verdicts["divide by zero"].answer == "no"


def test_tier1_is_skipped_when_tier0_decides_everything(cascade):
    # with no parameters and nothing risky, only "ok" stays open for Tier 1
    result = cascade.run("jpamb.cases.Simple.doNothing:()V")
    assert result.undecided() == ["ok"]


def test_tier1_proves_what_tier0_cannot(cascade):
    # array[1] = 1 on an array of length 2: the instruction is there (Tier 0
    # cannot say no), but the intervals prove it in bounds
    result = cascade.run("jpamb.cases.Arrays.arrayInBounds:()V")
    assert result.verdicts["out of bounds"].answer == "no"
    assert result.verdicts["out of bounds"].tier == 1


def test_tier0_constants_reach_the_widening(cascade):
    # for (i = 0; i != 8; i++) array[i] = i;
    # only provable with threshold widening, i.e. with K from Tier 0
    result = cascade.run("jpamb.cases.Group21Cases.arrayFillUntilEqual:()V")
    assert 8 in result.constants
    assert result.verdicts["out of bounds"] == result.verdicts["out of bounds"].__class__("no", 1)


def test_undecided_queries_keep_the_alarms(cascade):
    # return 1 / n;  neither tier can prove it, and Tier 1 says where
    result = cascade.run("jpamb.cases.Simple.divideByN:(I)I")
    assert "divide by zero" in result.undecided()
    (alarm,) = result.tier1.unproven("divide by zero")
    assert alarm.line == 46
