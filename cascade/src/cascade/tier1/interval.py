"""The abstract domain of Tier 1: intervals for ints, and Ref for arrays.

Interval and Ref live together because joining an unassigned local (an empty
interval) with an array reference needs both.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Self

import jvm
import jvm.state as jvms

from .lattice import Abstraction, Lattice


INT_MIN = -(2**31)
INT_MAX = 2**31 - 1
    
@dataclass(frozen=True)
class Interval(Abstraction, Lattice):
    min: int
    max: int

    def __post_init__(self):
        # Every empty interval - intervals where min > max - is bottom (empty interval), 
        # so that == compares empty intervals correctly.
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
    def alpha(cls, values: Iterable[jvms.StackValue]) -> Self:
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
        if isinstance(other, Ref):
            return _mixed(self, other)
        return Interval(min(self.min, other.min), max(self.max, other.max))

    def __and__(self, other: "Interval") -> "Interval":
        return Interval(max(self.min, other.min), min(self.max, other.max))

    def __lt__(self, other: "Interval") -> bool:
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


    def compare(self, other: "Interval", opr: jvm.CmpOpr) -> "IntervalSplit":
        """Split on `self opr other`: what each operand can be when the
        condition is true, and when it is false."""
        return IntervalSplit(
            if_true=_assume(self, other, opr),
            if_false=_assume(self, other, OPPOSITE[opr]),
        )

    def widen(self, other: "Interval", K: Iterable[int] = ()) -> "Interval":
        if isinstance(other, Ref):
            return _mixed(self, other)
        if self.is_bot:
            return other
        if other.is_bot:
            return self

        lo = self.min
        if other.min < self.min:
            lo = max([k for k in K if k <= other.min] + [INT_MIN])

        hi = self.max
        if other.max > self.max:
            hi = min([k for k in K if k >= other.max] + [INT_MAX])

        return Interval(lo, hi)


@dataclass(frozen=True)
class Branch:
    left: Interval
    right: Interval

    @property
    def possible(self) -> bool:
        return not self.left.is_bot


@dataclass(frozen=True)
class IntervalSplit:
    if_true: Branch
    if_false: Branch


OPPOSITE = {
    jvm.CmpOpr.Eq: jvm.CmpOpr.Ne,
    jvm.CmpOpr.Ne: jvm.CmpOpr.Eq,
    jvm.CmpOpr.Lt: jvm.CmpOpr.Ge,
    jvm.CmpOpr.Ge: jvm.CmpOpr.Lt,
    jvm.CmpOpr.Gt: jvm.CmpOpr.Le,
    jvm.CmpOpr.Le: jvm.CmpOpr.Gt,
}


def _assume(a: Interval, b: Interval, opr: jvm.CmpOpr) -> Branch:
    """Shrink a and b to the values for which `a opr b` can be true.
    Returns two bottoms if it can never be true."""
    bot = Interval.bot()
    if a.is_bot or b.is_bot:
        return Branch(bot, bot)

    match opr:
        case jvm.CmpOpr.Lt:
            a2 = a & Interval(INT_MIN, b.max - 1)
            b2 = b & Interval(a.min + 1, INT_MAX)
        case jvm.CmpOpr.Le:
            a2 = a & Interval(INT_MIN, b.max)
            b2 = b & Interval(a.min, INT_MAX)
        case jvm.CmpOpr.Gt:
            flipped = _assume(b, a, jvm.CmpOpr.Lt)
            a2, b2 = flipped.right, flipped.left
        case jvm.CmpOpr.Ge:
            flipped = _assume(b, a, jvm.CmpOpr.Le)
            a2, b2 = flipped.right, flipped.left
        case jvm.CmpOpr.Eq:
            a2 = b2 = a & b
        case jvm.CmpOpr.Ne:
            a2 = _remove(a, b.min) if b.min == b.max else a
            b2 = _remove(b, a.min) if a.min == a.max else b

    if a2.is_bot or b2.is_bot:
        return Branch(bot, bot)
    return Branch(a2, b2)


def _remove(a: Interval, n: int) -> Interval:
    if a.min == n:
        return Interval(a.min + 1, a.max)  # becomes bottom if a was [n, n]
    if a.max == n:
        return Interval(a.min, a.max - 1)
    return a


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
        return Interval(_trem(a.min, b.min), _trem(a.min, b.min))
    m = max(abs(b.min), abs(b.max)) - 1 
    lo = 0 if a.min >= 0 else -min(m, -a.min)
    hi = 0 if a.max <= 0 else min(m, a.max)
    return Interval(lo, hi)


@dataclass(frozen=True)
class Ref:
    null: bool
    length: Interval

    def __or__(self, other: "Ref") -> "Ref":
        if isinstance(other, Interval):
            return _mixed(other, self)
        return Ref(self.null or other.null, self.length | other.length)

    def widen(self, other: "Ref", K: Iterable[int] = ()) -> "Ref":
        if isinstance(other, Interval):
            return _mixed(other, self)
        return Ref(self.null or other.null, self.length.widen(other.length, K))

    def __str__(self):
        text = f"len={self.length}"
        return f"null|{text}" if self.null else text


def _mixed(interval: Interval, ref: Ref) -> Ref:
    if interval.is_bot:
        return ref
    raise NotImplementedError("an int and a reference in the same variable")
