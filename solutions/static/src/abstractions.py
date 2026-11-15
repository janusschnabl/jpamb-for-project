from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal, Self

import jvm
import jvm.state as jvms


class Poset(ABC):
    @abstractmethod
    def __eq__(self, other: Self) -> bool: ...

    @abstractmethod
    def __lt__(self, other: Self) -> bool: ...

    def __le__(self, other: Self) -> bool:
        return self == other or self < other

    @abstractmethod
    def __gt__(self, other: Self) -> bool: ...

    def __ge__(self, other: Self) -> bool:
        return self == other or self > other


def is_reflexive(a: Poset):
    # Checking if the relation is reflexive (a == a)
    assert a == a, f"Reflexivity check failed: Element {a} is not related to itself."  # noqa: PLR0124


def is_antisymmetric(a: Poset, b: Poset):
    if a != b:
        # Checking that if a <= b and b <= a, then a must equal b
        assert not (a <= b <= a), (
            f"Antisymmetry violation: Found elements where {a} <= {b} and {b} <= {a}, "
            f"but {a} != {b}."
        )


def is_transitive(a: Poset, b: Poset, c: Poset):
    if a <= b <= c:
        # Checking that if a <= b and b <= c, then a <= c
        assert a <= c, (
            f"Transitivity violation: Found path {a} <= {b} and {b} <= {c}, "
            f"but {a} is not related to {c}."
        )


def is_poset(a: Poset, b: Poset, c: Poset):
    for x in [a, b, c]:
        is_reflexive(x)

    for x in [b, c]:
        is_antisymmetric(a, x)

    is_transitive(a, b, c)


class Lattice(Poset):
    @classmethod
    @abstractmethod
    def top(cls) -> Self:
        raise NotImplementedError(f"top: {cls}")

    @classmethod
    def bot(cls) -> Self:
        return cls.abstract([])

    @abstractmethod
    def __or__(self, other: Self) -> Self: ...

    @abstractmethod
    def __and__(self, other: Self) -> Self: ...


def is_lattice_identities(a: Lattice):
    # Top element identity checks
    assert (a | a.top()) == a.top(), (
        f"Top identity fail: ({a} | {a.top()}) -> {a | a.top()} != {a.top()}"
    )
    assert (a.top() | a) == a.top(), (
        f"Top identity fail (commute): ({a.top()} | {a}) != {a.top()}"
    )
    assert (a & a.top()) == a, f"Top identity fail (meet): ({a} & {a.top()}) != {a}"
    assert (a.top() & a) == a, (
        f"Top identity fail (meet commute): ({a.top()} & {a}) != {a}"
    )

    # Bottom element identity checks
    assert (a & a.bot()) == a.bot(), (
        f"Bottom identity fail: ({a} & {a.bot()}) != {a.bot()}"
    )
    assert (a.bot() & a) == a.bot(), (
        f"Bottom identity fail (commute): ({a.bot()} & {a}) != {a.bot()}"
    )
    assert (a.bot() | a) == a, f"Bottom identity fail (join): ({a.bot()} | {a}) != {a}"
    assert (a | a.bot()) == a, (
        f"Bottom identity fail (join commute): ({a} | {a.bot()}) != {a}"
    )


def is_lattice(a: Lattice, b: Lattice, c: Lattice):
    for x in [a, b, c]:
        is_lattice_identities(x)

    if not (a | b <= c):
        # Calculate values for the error message
        assert not (a <= c and b <= c), (
            f"Upper bound check failed: ({a} | {b}) -> {a | b} is not <= {c}. "
            f"Check individual bounds: {a <= c=}, {b <= c=}."
        )

    if not (c <= a & b):
        # Calculate values for the error message
        assert not (c <= a and c <= b), (
            f"Lower bound check failed: {c} is not <= ({a} & {b}) -> {a & b}. "
            f"Check individual bounds: {c <= a=}, {c <= b=}."
        )


class Abstraction(ABC):
    """This is the minimal interface for an abstraction."""

    @classmethod
    @abstractmethod
    def abstract(cls, values: Iterable[jvms.StackValue]) -> Self:
        raise NotImplementedError(f"abstract: {cls}")

    @abstractmethod
    def __contains__(self, value: jvms.StackValue) -> bool: ...


def is_galoi(a: set[jvms.StackValue], b: Abstraction):
    alpha_a = b.abstract(a)

    for value in a:
        assert value in alpha_a, f"{value} not in {a}"

    if alpha_a <= b:
        for value in a:
            assert value in b, f"{value} not in {b}"


type Sign = Literal[-1, 0, 1]


def to_sign(value: jvms.StackValue) -> Sign:
    match value:
        case jvms.StackInt(v):
            return (v > 0) - (v < 0)
        case a:
            raise NotImplementedError(f"Unsupported value {value!r}")


@dataclass(frozen=True, order=True)
class SignSet(Abstraction, Lattice):
    signs: frozenset[Sign]

    def __str__(self):
        return f"{{{''.join(z for z, b in zip('-0+', [-1, 0, 1]) if b in self.signs)}}}"

    def __sexpr__(self):
        return str(self)

    @classmethod
    def from_sign(cls, code):
        return cls(frozenset(b for z, b in zip("-0+", [-1, 0, 1]) if z in code))

    @classmethod
    def abstract(cls, values: Iterable[jvms.StackValue]) -> Self:
        signs = set()
        for value in values:
            signs.add(to_sign(value))
        return cls(frozenset(signs))

    def __contains__(self, value: jvms.StackValue) -> bool:
        return to_sign(value) in self.signs

    @classmethod
    def top(cls) -> bool:
        return cls(frozenset([-1, 0, 1]))

    def __or__(self, other: "SignSet") -> "SignSet":
        if not isinstance(other, SignSet):
            return NotImplemented

        return SignSet(self.signs | other.signs)

    def __and__(self, other: "SignSet") -> "SignSet":
        if not isinstance(other, SignSet):
            return NotImplemented

        return SignSet(self.signs & other.signs)

    def arithmetic(
        self, other: "SignSet", opr: jvm.BinaryOpr
    ) -> tuple["SignSet", set[str]]:
        match opr:
            case jvm.BinaryOpr.Add:
                output = set()
                if 1 in self.signs:
                    output.add(1)
                    if -1 in other.signs:
                        output.update([0, -1])

                if -1 in self.signs:
                    output.add(-1)
                    if 1 in other.signs:
                        output.update([0, 1])

                if 0 in self.signs:
                    output.update(other.signs)

                return (SignSet(output), set())
            case _:
                raise NotImplementedError(f"TODO: {opr}")

    def compare(self, other: "SignSet", opr: jvm.CmpOpr) -> Iterable[bool]:
        match opr:
            case jvm.CmpOpr.Le:
                cases = set()
                for x in self.signs:
                    for y in other.signs:
                        if x == 0 or y == 0:
                            cases.add(x <= y)
                            continue
                        if x <= y:
                            cases.add(True)
                        if x >= y:
                            cases.add(False)
                return cases
            case _:
                raise NotImplementedError(f"TODO: {opr}")


from collections.abc import Iterable
from dataclasses import dataclass
from typing import Self

INT_MIN = -(2**31)
INT_MAX = 2**31 - 1

@dataclass(frozen=True)
class Interval(Abstraction, Lattice):
    min: int
    max: int

    def __post_init__(self):
        # Every empty interval ([5, 3], [9, -1], ...) is turned into the one
        # canonical bottom, so that == compares empty intervals correctly.
        if self.min > self.max:
            object.__setattr__(self, "min", INT_MAX)
            object.__setattr__(self, "max", INT_MIN)

    @property
    def is_bot(self) -> bool:
        return self.min > self.max

    def __str__(self):
        if self.is_bot:
            return "⊥"
        return f"[{self.min}, {self.max}]"

    def __sexpr__(self):
        return str(self)

    @classmethod
    def abstract(cls, values: Iterable[jvms.StackValue]) -> Self:
        numbers = []
        for value in values:
            match value:
                case jvms.StackInt(v):
                    numbers.append(v)
                case _:
                    raise NotImplementedError(f"Unsupported value {value!r}")

        if not numbers:
            return cls(INT_MAX, INT_MIN)

        return cls(min(numbers), max(numbers))

    def __contains__(self, value: jvms.StackValue) -> bool:
        match value:
            case jvms.StackInt(v):
                return self.min <= v <= self.max
            case _:
                return False

    @classmethod
    def top(cls) -> Self:
        return cls(INT_MIN, INT_MAX)

    def __or__(self, other: "Interval") -> "Interval":
        return Interval(min(self.min, other.min), max(self.max, other.max))

    def __and__(self, other: "Interval") -> "Interval":
        return Interval(max(self.min, other.min), min(self.max, other.max))

    def __lt__(self, other: "Interval") -> bool:
        # strictly smaller: inside other, and not equal to it
        return other.min <= self.min and self.max <= other.max and self != other

    def __gt__(self, other: "Interval") -> bool:
        return other < self
    
    def arithmetic(
        self, other: "Interval", opr: jvm.BinaryOpr
    ) -> tuple["Interval", set[str]]:
        if self.is_bot or other.is_bot:
            return (Interval.bot(), set())

        a, b = self, other
        match opr:
            case jvm.BinaryOpr.Add:
                return (_fit(a.min + b.min, a.max + b.max), set())

            case jvm.BinaryOpr.Sub:
                return (_fit(a.min - b.max, a.max - b.min), set())

            case jvm.BinaryOpr.Mul:
                corners = [a.min * b.min, a.min * b.max, a.max * b.min, a.max * b.max]
                return (_fit(min(corners), max(corners)), set())

            case jvm.BinaryOpr.Div | jvm.BinaryOpr.Rem:
                errors = {"divide by zero"} if b.min <= 0 <= b.max else set()
                negative = b & Interval(INT_MIN, -1)
                positive = b & Interval(1, INT_MAX)
                result = Interval.bot()
                for part in (negative, positive):
                    if part.is_bot:
                        continue
                    if opr == jvm.BinaryOpr.Div:
                        result = result | _div(a, part)
                    else:
                        result = result | _rem(a, part)
                return (result, errors)

            case _:
                raise NotImplementedError(f"TODO: {opr}")

    def compare(
        self, other: "Interval", opr: jvm.CmpOpr
    ) -> tuple["Interval", "Interval"]:
        return 

def _fit(lo: int, hi: int) -> Interval:
    if lo < INT_MIN or hi > INT_MAX:
        return Interval.top()
    return Interval(lo, hi)

def _tdiv(x: int, y: int) -> int:
    q = abs(x) // abs(y)
    return q if (x < 0) == (y < 0) else -q


def _trem(x: int, y: int) -> int:
    return x - _tdiv(x, y) * y


def _div(a: Interval, b: Interval) -> Interval:
    corners = [_tdiv(x, y) for x in (a.min, a.max) for y in (b.min, b.max)]
    return _fit(min(corners), max(corners))


def _rem(a: Interval, b: Interval) -> Interval:
    if a.min == a.max and b.min == b.max:
        return Interval(_trem(a.min, b.min), _trem(a.min, b.min))  # both constants: exact
    m = max(abs(b.min), abs(b.max)) - 1  # the largest possible |result|
    lo = 0 if a.min >= 0 else -min(m, -a.min)
    hi = 0 if a.max <= 0 else min(m, a.max)
    return Interval(lo, hi)
