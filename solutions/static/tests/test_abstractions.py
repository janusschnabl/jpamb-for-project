import abstractions as ab
import pytest
from hypothesis import given
from hypothesis import strategies as st

import jvm
import jvm.state as jvms


def st_i32():
    return st.integers(min_value=-(2**31) - 1, max_value=2**31)


def st_u32():
    return st.integers(min_value=0, max_value=2**32)


def st_stack_ints():
    return st_i32().map(jvms.StackInt)


def st_stack_refs():
    return st_u32().map(jvms.StackReference)


def st_signset():
    return (
        st.sets(st.integers(min_value=-1, max_value=1)).map(frozenset).map(ab.SignSet)
    )


@given(st_signset(), st_signset(), st_signset())
def test_signset_is_poset(a: ab.SignSet, b: ab.SignSet, c: ab.SignSet):
    ab.is_poset(a, b, c)


@given(st_signset(), st_signset(), st_signset())
def test_signset_is_lattice(a: ab.SignSet, b: ab.SignSet, c: ab.SignSet):
    ab.is_lattice(a, b, c)


@given(st.sets(st_stack_ints()), st_signset())
def test_signset_is_galoi(a: set[jvms.StackInt], b: ab.SignSet):
    ab.is_galoi(a, b)


def arithmetic(opr, x, y):
    match opr:
        case jvm.BinaryOpr.Add:
            return jvms.StackInt(x.value + y.value)
        case _:
            raise NotImplementedError("TODO")


@given(
    st.sampled_from([jvm.BinaryOpr.Add]),
    st.sets(st_stack_ints()),
    st.sets(
        st_stack_ints(),
    ),
)
def test_signset_arithmetic(
    opr: jvm.BinaryOpr, xs: set[jvms.StackInt], ys: set[jvms.StackInt]
):
    real = ab.SignSet.abstract(arithmetic(opr, x, y) for x in xs for y in ys)
    (abstracted, _errs) = ab.SignSet.abstract(xs).arithmetic(
        ab.SignSet.abstract(ys), opr
    )
    assert real <= abstracted


def compare(opr, x, y):
    match opr:
        case jvm.CmpOpr.Le:
            return x.value <= y.value
        case _:
            raise NotImplementedError("TODO")


@given(
    st.sampled_from([jvm.CmpOpr.Le]),
    st.sets(st_stack_ints()),
    st.sets(
        st_stack_ints(),
    ),
)
def test_signset_compare(
    opr: jvm.CmpOpr, xs: set[jvms.StackInt], ys: set[jvms.StackInt]
):
    real = {compare(opr, x, y) for x in xs for y in ys}
    abstracted = set(ab.SignSet.abstract(xs).compare(ab.SignSet.abstract(ys), opr))
    assert real <= abstracted


def st_int_bound():
    """A bound for an interval: any JVM int, but with extra weight on small
    numbers (so that random intervals actually overlap) and on the extremes."""
    return st.one_of(
        st.integers(min_value=-20, max_value=20),
        st.integers(min_value=ab.INT_MIN, max_value=ab.INT_MAX),
        st.sampled_from([ab.INT_MIN, ab.INT_MAX]),
    )


@st.composite
def st_interval(draw):
    # Two random bounds in random order: when min > max this is the empty
    # interval, so bottom is generated too.
    return ab.Interval(draw(st_int_bound()), draw(st_int_bound()))


@given(st_interval(), st_interval(), st_interval())
def test_interval_is_poset(a: ab.Interval, b: ab.Interval, c: ab.Interval):
    ab.is_poset(a, b, c)


@given(st_interval(), st_interval(), st_interval())
def test_interval_is_lattice(a: ab.Interval, b: ab.Interval, c: ab.Interval):
    ab.is_lattice(a, b, c)


@given(st_interval(), st_interval())
def test_interval_join_and_meet_are_bounds(a: ab.Interval, b: ab.Interval):
    # is_lattice only checks that the join is the LEAST upper bound,
    # not that it is an upper bound at all.  This checks the rest.
    assert a <= (a | b) and b <= (a | b)
    assert (a & b) <= a and (a & b) <= b


@given(st.sets(st_int_bound().map(jvms.StackInt)), st_interval())
def test_interval_is_galoi(a: set[jvms.StackInt], b: ab.Interval):
    ab.is_galoi(a, b)


# ---------------------------------------------------------------- interval arithmetic


def to_i32(v: int) -> int:
    """Keep the low 32 bits, like the JVM does."""
    v = v & 0xFFFFFFFF
    if v >= 2**31:
        v = v - 2**32
    return v


def jvm_arithmetic(opr: jvm.BinaryOpr, x: int, y: int) -> int:
    """What the JVM computes (y != 0 for Div and Rem)."""
    match opr:
        case jvm.BinaryOpr.Add:
            return to_i32(x + y)
        case jvm.BinaryOpr.Sub:
            return to_i32(x - y)
        case jvm.BinaryOpr.Mul:
            return to_i32(x * y)
        case jvm.BinaryOpr.Div:
            q = abs(x) // abs(y)
            return to_i32(q if (x < 0) == (y < 0) else -q)  # rounds towards zero
        case jvm.BinaryOpr.Rem:
            q = abs(x) // abs(y)
            return x - (q if (x < 0) == (y < 0) else -q) * y  # sign of x


@given(
    st.sampled_from(list(jvm.BinaryOpr)),
    st.sets(st_int_bound(), max_size=5),
    st.sets(st_int_bound(), max_size=5),
)
def test_interval_arithmetic(opr: jvm.BinaryOpr, xs: set[int], ys: set[int]):
    """Soundness: every concrete result lies in the abstract result, and a
    division by zero that can happen is reported."""
    a = ab.Interval.abstract(map(jvms.StackInt, xs))
    b = ab.Interval.abstract(map(jvms.StackInt, ys))
    result, errors = a.arithmetic(b, opr)
    for x in xs:
        for y in ys:
            if opr in (jvm.BinaryOpr.Div, jvm.BinaryOpr.Rem) and y == 0:
                assert "divide by zero" in errors
            else:
                r = jvm_arithmetic(opr, x, y)
                assert jvms.StackInt(r) in result, f"{x} {opr} {y} = {r} not in {result}"


@given(st.sampled_from(list(jvm.BinaryOpr)), st_interval())
def test_interval_arithmetic_with_bottom(opr: jvm.BinaryOpr, a: ab.Interval):
    """No value combined with any value is no value."""
    bot = ab.Interval.bot()
    assert a.arithmetic(bot, opr)[0] == bot
    assert bot.arithmetic(a, opr)[0] == bot
