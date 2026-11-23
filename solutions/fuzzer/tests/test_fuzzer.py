import pytest
from fuzzer import fuzz
from mutators import Dictionary, MutationConfig

import jpamb
import jvm

suite, eff = jpamb.setup()
bc = jpamb.Bytecode(suite, eff, {})


def method(name):
    return jvm.AbsMethodID.decode(f"jpamb.cases.{name}")


DIVIDE = "Simple.divideByN:(I)I"
HARD = "Simple.divideByNMinus10054203:(I)I"


def test_finds_divide_by_zero():
    r = fuzz(bc, method(DIVIDE), budget=100, seed=0)
    assert "divide by zero" in r.witnesses


def test_one_run_finds_several_errors():
    k = Dictionary(ints=(104, 101, 108, 111))  # h, e, l, o
    r = fuzz(
        bc, method("Arrays.arraySpellsHello:([C)V"), budget=500, seed=0, dictionary=k
    )
    assert {"out of bounds", "assertion error"} <= set(r.witnesses)


def test_dictionary_finds_what_blind_mutation_cannot():
    with_k = fuzz(bc, method(HARD), 2000, 0, dictionary=Dictionary(ints=(10054203,)))
    without_k = fuzz(bc, method(HARD), 2000, 0)
    assert "divide by zero" in with_k.witnesses
    assert "divide by zero" not in without_k.witnesses


def test_observed_inputs_include_non_crashing_ones():
    r = fuzz(bc, method(DIVIDE), budget=200, seed=0)
    assert {"ok", "divide by zero"} <= {outcome for _, outcome in r.observed}


def test_same_seed_gives_same_result():
    a = fuzz(bc, method(HARD), 300, 5)
    b = fuzz(bc, method(HARD), 300, 5)
    assert a.observed == b.observed and a.witnesses == b.witnesses


def test_different_seeds_differ():
    a = fuzz(bc, method(HARD), 100, 1)
    b = fuzz(bc, method(HARD), 100, 2)
    assert a.observed != b.observed


def test_tiny_input_space_stops_early():
    r = fuzz(bc, method("Simple.assertBoolean:(Z)V"), budget=1000, seed=0)
    assert r.executions == 2  # only false and true exist
    assert set(r.witnesses) == {"assertion error"}


def test_empty_focus_means_nothing_counts_as_progress():
    r = fuzz(bc, method(DIVIDE), budget=50, seed=0, focus=set())
    assert r.corpus_size == 0
    assert "divide by zero" in r.witnesses


def test_time_limit_stops_the_run():
    r = fuzz(bc, method(HARD), budget=10**9, seed=0, time_limit=0.2)
    assert 0 < r.executions < 10**9


SECRET = "Group21Cases.secretThenDivide:([C)I"


def _built(name):
    try:
        bc.getmethod(method(name))
        return True
    except Exception:
        return False


needs_fuzzing_class = pytest.mark.skipif(
    not _built(SECRET), reason="the Fuzzing benchmark class is not built on this branch"
)


@needs_fuzzing_class
def test_finds_the_secret_with_resize_and_dictionary():
    k = Dictionary(ints=(6, 115, 101, 99, 114, 116))
    r = fuzz(bc, method(SECRET), budget=5000, seed=0, dictionary=k)
    assert "divide by zero" in r.witnesses


def test_unguided_corpus_stays_empty():
    r = fuzz(bc, method(HARD), budget=300, seed=0, guided=False)
    assert r.corpus_size == 0
    assert r.executions > 1  # It still ran inputs, it just never built on them


def test_guided_corpus_is_no_bigger_than_the_coverage():
    # Every corpus entry reached at least one new instruction, and every such
    # instruction is in the coverage, so entries cannot outnumber instructions.
    r = fuzz(bc, method(HARD), budget=300, seed=0)
    assert 0 < r.corpus_size <= len(r.coverage)


def test_witness_records_which_run_found_it():
    k = Dictionary(ints=(104, 101, 108, 111))
    r = fuzz(
        bc, method("Arrays.arraySpellsHello:([C)V"), budget=500, seed=0, dictionary=k
    )
    assert not r.failures  # Otherwise `observed` falls out of step with run numbers
    assert r.witnesses
    for w in r.witnesses.values():
        assert r.observed[w.execution - 1] == (w.input, w.outcome)


def test_default_switches_reproduce_the_default_run():
    a = fuzz(bc, method(HARD), 300, 5)
    b = fuzz(bc, method(HARD), 300, 5, guided=True, config=MutationConfig())
    assert a == b
