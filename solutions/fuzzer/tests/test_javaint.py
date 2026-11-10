from javaint import INT_MAX, INT_MIN, java_div, java_rem, to_i16, to_i32, to_u16


def test_wraparound():
    assert to_i32(INT_MAX + 1) == INT_MIN
    assert to_i32(INT_MIN - 1) == INT_MAX


def test_division_truncates_toward_zero():
    assert java_div(7, 2) == 3
    assert java_div(-7, 2) == -3
    assert java_div(7, -2) == -3
    assert java_div(-7, -2) == 3


def test_remainder_follows_dividend():
    assert java_rem(7, 2) == 1
    assert java_rem(-7, 2) == -1
    assert java_rem(7, -2) == 1
    assert java_rem(-7, -2) == -1


def test_min_value_edge_cases():
    assert java_div(INT_MIN, -1) == INT_MIN
    assert java_rem(INT_MIN, -1) == 0


def test_short_and_char_casts():
    assert to_i16(32768) == -32768
    assert to_i16(-32769) == 32767
    assert to_u16(-1) == 65535