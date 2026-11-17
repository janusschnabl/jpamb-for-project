from cascade.tier0.constant_mining import extract_constants

import jvm


def test_collects_pushed_int_literals():
    opcodes = [
        jvm.Push(offset=0, type=jvm.Int(), value=1),
        jvm.Push(offset=1, type=jvm.Int(), value=0),
        jvm.Binary(offset=2, type=jvm.Int(), operant=jvm.BinaryOpr.Div),
    ]

    assert extract_constants(opcodes) == {0, 1}


def test_collects_iinc_amount():
    opcodes = [jvm.Incr(offset=0, index=1, amount=42)]

    assert extract_constants(opcodes) == {42}


def test_ignores_non_integer_pushes():
    opcodes = [
        jvm.Push(offset=0, type=jvm.Reference(), value=0),
        jvm.Push(offset=1, type=jvm.Object(jvm.ClassName.from_parts("java", "lang", "String")), value="hello"),
    ]

    assert extract_constants(opcodes) == set()


def test_deduplicates_repeated_constants():
    opcodes = [
        jvm.Push(offset=0, type=jvm.Int(), value=7),
        jvm.Push(offset=1, type=jvm.Int(), value=7),
    ]

    assert extract_constants(opcodes) == {7}


def test_collects_negative_literals():
    # e.g. Arrays.arrayContentAboveMinus13's `array[i] >= -13`
    opcodes = [jvm.Push(offset=0, type=jvm.Int(), value=-13)]

    assert extract_constants(opcodes) == {-13}
