import random

from javaint import INT_MAX, INT_MIN
from mutators import (
    MAX_LENGTH,
    Dictionary,
    MutationConfig,
    initial_input,
    mutate_array,
    mutate_input,
    mutate_string,
)

import jvm
from jpamb.case import Array, Boolean, Char, Input, Int, String

START = Input(
    (
        Int(0),
        Boolean(False),
        Char("a"),
        Array(jvm.Int(), ()),
        Array(jvm.Char(), ()),
        String(""),
    )
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
    ints = {
        v.value for m in mutations(4, K, 5000) for v in m.values if isinstance(v, Int)
    }
    strings = {
        v.value
        for m in mutations(4, K, 5000)
        for v in m.values
        if isinstance(v, String)
    }
    assert ints & {4241, 4242, 4243}
    assert "hello" in strings


def test_works_without_a_dictionary():
    assert len(list(mutations(5, Dictionary()))) == 2000


def test_initial_input_matches_the_signature():
    m = jvm.AbsMethodID.decode("jpamb.cases.Arrays.arraySpellsHello:([C)V")
    assert initial_input(m) == Input((Array(jvm.Char(), ()),))
    m = jvm.AbsMethodID.decode("jpamb.cases.Simple.divideZeroByZero:(II)I")
    assert initial_input(m) == Input((Int(0), Int(0)))


def test_resize_can_jump_to_a_dictionary_length():
    rng = random.Random(0)
    empty = Array(jvm.Char(), ())
    lengths = {
        len(mutate_array(rng, empty, Dictionary(ints=(6,))).values) for _ in range(300)
    }
    assert 6 in lengths


def test_resize_never_exceeds_the_limit():
    rng = random.Random(1)
    d = Dictionary(ints=(6, 1000, -3))
    array, text = Array(jvm.Int(), (1, 2, 3)), "abc"
    for _ in range(1000):
        array = mutate_array(rng, array, d)
        text = mutate_string(rng, text, d)
        assert len(array.values) <= MAX_LENGTH
        assert len(text) <= MAX_LENGTH


def changed_positions(a, b):
    return sum(x != y for x, y in zip(a.values, b.values))


def test_bursts_change_many_arguments_at_once():
    start = Input(tuple(Int(0) for _ in range(5)))
    rng = random.Random(3)
    widest = max(
        changed_positions(start, mutate_input(rng, start, Dictionary()))
        for _ in range(2000)
    )
    assert widest >= 4


def test_without_bursts_at_most_three_arguments_change():
    config = MutationConfig(burst_probability=0.0)
    start = Input(tuple(Int(0) for _ in range(5)))
    rng = random.Random(3)
    widest = max(
        changed_positions(start, mutate_input(rng, start, Dictionary(), config))
        for _ in range(2000)
    )
    assert widest <= 3


TEXT_LENGTH = 8  # Length of the starting string in the three tests below


def _length_changes(config: MutationConfig, rounds: int = 500) -> list[int]:
    rng = random.Random(0)
    start = Input((String("a" * TEXT_LENGTH),))
    changes = []
    for _ in range(rounds):
        match mutate_input(rng, start, Dictionary(), config).values[0]:
            case String(v):
                changes.append(abs(len(v) - TEXT_LENGTH))
    return changes


def test_without_resize_or_bursts_length_changes_are_small():
    # At most 3 mutations per round, each moving the length by at most 1
    config = MutationConfig(resize=False, burst_probability=0.0)
    assert max(_length_changes(config)) <= 3


def test_resize_allows_big_length_jumps():
    config = MutationConfig(resize=True, burst_probability=0.0)
    assert max(_length_changes(config)) > 3


def test_bursts_allow_bigger_changes_than_single_moves():
    config = MutationConfig(resize=False, burst_probability=1.0)
    assert max(_length_changes(config)) > 3
