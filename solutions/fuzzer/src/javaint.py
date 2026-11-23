"""Java 32-bit integer semantics, independent of any interpreter."""

INT_MIN = -(1 << 31)
INT_MAX = (1 << 31) - 1


def to_i32(v: int) -> int:
    v &= 0xFFFFFFFF
    return v - (1 << 32) if v >= (1 << 31) else v


def to_i16(v: int) -> int:
    v &= 0xFFFF
    return v - (1 << 16) if v >= (1 << 15) else v


def to_u16(v: int) -> int:
    return v & 0xFFFF


def java_div(a: int, b: int) -> int:
    """Truncating division. The caller checks b != 0 first."""
    q = abs(a) // abs(b)
    return to_i32(-q if (a < 0) != (b < 0) else q)


def java_rem(a: int, b: int) -> int:
    """Remainder with the sign of the dividend. The caller checks b != 0 first."""
    return to_i32(a - java_div(a, b) * b)