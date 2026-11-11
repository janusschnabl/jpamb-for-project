import random

from javaint import INT_MAX, INT_MIN
from mutators import MAX_LENGTH, Dictionary, initial_input, mutate_input

import jvm
from jpamb.case import Array, Boolean, Char, Input, Int, String

START = Input(
    (Int(0), Boolean(False), Char("a"), Array(jvm.Int(), ()),
     Array(jvm.Char(), ()), String(""))
)
K = Dictionary(ints=(4242, 104, 101), strings=("hello",))


def mutations(seed, d, n=2000):
    """A chain of n mutations, each applied to the previous result."""
    rng = random.Random(seed)
    current = START
    for _ in range(n):
        current = mutate_input(rng, current, d)
        yield current


def test_types_are_preserved():
    shape = [(type(v), getattr(v, "contains", None)) for v in START.values]
    for m in mutations(0, K):
        assert [(type(v), getattr(v, "contains", None)) for v in m.values] == shape


def test_ints_stay_in_range():
    for m in mutations(1, K):
        for v in m.values:
            if isinstance(v, Int):
                assert INT_MIN <= v.value <= INT_MAX


def test_lengths_are_bounded():
    for m in mutations(2, K):
        for v in m.values:
            if isinstance(v, (Array, String)):
                assert len(v.values if isinstance(v, Array) else v.value) <= MAX_LENGTH


def test_every_input_can_be_written_and_read_back():
    for m in mutations(3, K):
        assert Input.decode(m.encode()) == m


def test_same_seed_gives_same_mutations():
    assert list(mutations(7, K, 300)) == list(mutations(7, K, 300))


def test_different_seeds_differ():
    assert list(mutations(7, K, 300)) != list(mutations(8, K, 300))


def test_dictionary_values_show_up():
    ints = {v.value for m in mutations(4, K, 5000) for v in m.values if isinstance(v, Int)}
    strings = {v.value for m in mutations(4, K, 5000) for v in m.values if isinstance(v, String)}
    assert ints & {4241, 4242, 4243}
    assert "hello" in strings


def test_works_without_a_dictionary():
    assert len(list(mutations(5, Dictionary()))) == 2000


def test_initial_input_matches_the_signature():
    m = jvm.AbsMethodID.decode("jpamb.cases.Arrays.arraySpellsHello:([C)V")
    assert initial_input(m) == Input((Array(jvm.Char(), ()),))
    m = jvm.AbsMethodID.decode("jpamb.cases.Simple.divideZeroByZero:(II)I")
    assert initial_input(m) == Input((Int(0), Int(0)))