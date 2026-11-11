"""Type-aware mutation of method inputs. Depends only on jpamb, jvm and javaint."""

import random
from dataclasses import dataclass

from javaint import INT_MAX, INT_MIN, to_i32

import jvm
from jpamb.case import Array, Boolean, Char, Input, Int, String

MAX_LENGTH = 16    # Longest array or string we generate
BOUNDARY_INTS = (0, 1, -1, INT_MAX, INT_MIN)
PRINTABLE = "".join(chr(i) for i in range(32, 127) if chr(i) != "'")

@dataclass(frozen=True)
class Dictionary:
    """Constants mined from the code (the K from Tier 0). May be empty."""

    ints: tuple[int, ...] = ()
    strings: tuple[str, ...] = ()

def _dictionary_chars(d: Dictionary) -> list[str]:
    found = {chr(i) for i in d.ints if 32 <= i <= 126}
    found |= {ch for s in d.strings for ch in s}
    return sorted(ch for ch in found if ch in PRINTABLE)

def _dictionary_strings(d: Dictionary) -> list[str]:
    return sorted(s for s in d.strings if "'" not in s)

def mutate_int(rng: random.Random, value: int, d: Dictionary) -> int:
    moves = ["one", "small", "negate", "boundary", "bit", "random"]
    if d.ints:
        moves.append("constant")
    move = rng.choice(moves)
    if move == "one":
        new = value + rng.choice((-1, 1))
    elif move == "small":
        new = value + rng.randint(-16, 16)
    elif move == "negate":
        new = -value
    elif move == "boundary":
        new = rng.choice(BOUNDARY_INTS)
    elif move == "bit":
        new = value ^ (1 << rng.randrange(32))
    elif move == "constant":
        new = rng.choice(d.ints) + rng.choice((-1, 0, 1))
    else:
        new = rng.randint(INT_MIN, INT_MAX)
    return to_i32(new)

def mutate_char(rng: random.Random, value: str, d: Dictionary) -> str:
    chars = _dictionary_chars(d)
    moves = ["step", "random"] + (["constant"] if chars else [])
    move = rng.choice(moves)
    if move == "step":
        new = chr(ord(value) + rng.choice((-1, 1)))
        return new if new in PRINTABLE else rng.choice(PRINTABLE)
    if move == "constant":
        return rng.choice(chars)
    return rng.choice(PRINTABLE)

def mutate_string(rng: random.Random, value: str, d: Dictionary) -> str:
    strings = _dictionary_strings(d)
    moves = []
    if len(value) < MAX_LENGTH:
        moves.append("insert")
    if value:
        moves += ["change", "delete"]
    if strings:
        moves += ["replace", "splice"]
    move = rng.choice(moves)
    if move == "insert":
        i = rng.randint(0, len(value))
        return value[:i] + rng.choice(PRINTABLE) + value[i:]
    if move == "change":
        i = rng.randrange(len(value))
        return value[:i] + rng.choice(PRINTABLE) + value[i + 1 :]
    if move == "delete":
        i = rng.randrange(len(value))
        return value[:i] + value[i + 1 :]
    if move == "replace":
        return rng.choice(strings)
    i = rng.randint(0, len(value))
    return (value[:i] + rng.choice(strings) + value[i:])[:MAX_LENGTH]

def mutate_array(rng: random.Random, array: Array, d: Dictionary) -> Array:
    is_int = isinstance(array.contains, jvm.Int)
    mutate_element = mutate_int if is_int else mutate_char
    default = 0 if is_int else "a"
    values = list(array.values)

    moves = []
    if len(values) < MAX_LENGTH:
        moves.append("insert")
    if values:
        moves += ["change", "delete", "clear"]
    move = rng.choice(moves)

    if move == "insert":
        values.insert(rng.randint(0, len(values)), mutate_element(rng, default, d))
    elif move == "change":
        i = rng.randrange(len(values))
        values[i] = mutate_element(rng, values[i], d)
    elif move == "delete":
        del values[rng.randrange(len(values))]
    else:
        values = []
    return Array(array.contains, tuple(values))


def mutate_value(rng: random.Random, value, d: Dictionary):
    match value:
        case Int(v):
            return Int(mutate_int(rng, v, d))
        case Boolean(v):
            return Boolean(not v)
        case Char(v):
            return Char(mutate_char(rng, v, d))
        case String(v):
            return String(mutate_string(rng, v, d))
        case Array():
            return mutate_array(rng, value, d)
        case _:
            raise NotImplementedError(f"Cannot mutate {value!r}")


def mutate_input(rng: random.Random, input: Input, d: Dictionary) -> Input:
    """Mutate one to three arguments of an input (mostly one)."""
    values = list(input.values)
    if not values:
        return input
    for _ in range(rng.choice((1, 1, 1, 1, 2, 3))):
        i = rng.randrange(len(values))
        values[i] = mutate_value(rng, values[i], d)
    return Input(tuple(values))


def default_value(t: jvm.Type):
    match t:
        case jvm.Int():
            return Int(0)
        case jvm.Boolean():
            return Boolean(False)
        case jvm.Char():
            return Char("a")
        case jvm.Array(contains=jvm.Int()):
            return Array(jvm.Int(), ())
        case jvm.Array(contains=jvm.Char()):
            return Array(jvm.Char(), ())
        case jvm.Object(name=jvm.ClassName("java.lang.String")):
            return String("")
        case _:
            raise NotImplementedError(f"No default value for {t!r}")


def initial_input(methodid: jvm.AbsMethodID) -> Input:
    """The simplest valid input: zeros, false, empty arrays and strings."""
    return Input(tuple(default_value(t) for t in methodid.extension.params))