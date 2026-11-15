import sys
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass

from abstractions import INT_MAX, Interval, Ref

import jpamb
import sexpr
from jpamb import jvm
from jvm.state import PC, StackInt


@dataclass(frozen=True)
class State(sexpr.AsSExpr):
    locals: tuple[Interval | Ref, ...]
    stack: tuple[Interval | Ref, ...]

    def __post_init__(self):
        assert isinstance(self.locals, tuple)
        assert isinstance(self.stack, tuple)

    def __str__(self):
        return f"{', '.join(map(str, self.locals))}/{':'.join(map(str, self.stack))}"

    def __or__(self, other):
        assert isinstance(other, State), f"Expected State but got {other!r}"
        assert len(self.stack) == len(other.stack), "Stacks should be equal lenght"
        assert len(self.locals) == len(other.locals), "Locals should be equal lenght"

        return State(
            tuple(s1 | s2 for s1, s2 in zip(self.locals, other.locals)),
            tuple(s1 | s2 for s1, s2 in zip(self.stack, other.stack)),
        )

    def push(self, value: Interval | Ref):
        assert isinstance(value, (Interval, Ref)), f"Expected a value but got {value}"
        return State(self.locals, self.stack + (value,))

    def pop(self, number=1):
        return self.stack[-number:], State(self.locals, self.stack[:-number])

    def load(self, index):
        return self.locals[index]

    def store(self, index, value):
        return State(
            tuple(self.locals[:index]) + (value,) + tuple(self.locals[index + 1 :]),
            self.stack,
        )



def manystep(
    bc: jpamb.Bytecode,
    pc: PC,
    state: State,
) -> Iterable[tuple[PC, object] | str]:
    opr = bc[pc]
    match opr:
        case jvm.Get(static=True, field=field):
            # Hack - Only handle the assertion case
            assert field.extension.name == "$assertionsDisabled"

            # Hack - Assuming assertions are never disabled
            val = Interval.alpha([StackInt(0)])

            yield (pc + 1, state.push(val))

        case jvm.Ifz(condition=op, target=target):
            [val], after = state.pop(1)
            split = val.compare(Interval(0, 0), op)

            if split.if_true.possible:
                yield (pc % target, after)  # jump taken
            if split.if_false.possible:
                yield (pc + 1, after)  # fall through
                
        case jvm.Push(type=jvm.Int(), value=v):
            val = Interval.alpha([StackInt(v)])
            yield (pc + 1, state.push(val))

        case jvm.NewArray(type=t, dim=1):
            [size], after = state.pop(1)
            size = size & Interval(0, INT_MAX)
            if not size.is_bot:
                yield (pc + 1, after.push(Ref(null=False, length=size)))

        case jvm.Load(index=i):
            val = state.load(i)
            yield (pc + 1, state.push(val))

        case jvm.Dup(words=1):
            val = state.stack[-1]
            yield (pc + 1, state.push(val))

        case jvm.Goto(target=t):
            yield (pc % t, state)

        case jvm.Binary(operant=op):
            [v1, v2], after = state.pop(2)
            result, errors = v1.arithmetic(v2, op)
            yield from errors  # e.g. "divide by zero"
            if not result.is_bot:  # ⊥: nothing continues
                yield (pc + 1, after.push(result))

        case jvm.Return(type=None):
            yield "ok"

        case jvm.Return(type=t):
            # Hack -- we assume that we always return.
            yield "ok"

        case jvm.New(classname=jvm.ClassName("java.lang.AssertionError")):
            # Hack -- if we create an assertion error, we probably also throw it.
            yield "assertion error"

        case _:
            raise NotImplementedError(f"Instruction not handled: {opr}")


def initialstate(
    bc: jpamb.Bytecode,
    methodid: jvm.AbsMethodID,
    inputs: jpamb.Input | None,
) -> dict[PC, State]:
    method = bc.getmethod(methodid)
    locals = [Interval.bot()] * method.max_locals

    if inputs is None:
        # any input: use the range of each parameter's TYPE
        for i, p in enumerate(methodid.extension.params):
            match p:
                case jvm.Boolean():
                    locals[i] = Interval(0, 1)
                case jvm.Char():
                    locals[i] = Interval(0, 65535)
                case jvm.Short():
                    locals[i] = Interval(-(2**15), 2**15 - 1)
                case jvm.Byte():
                    locals[i] = Interval(-(2**7), 2**7 - 1)
                case jvm.Int():
                    locals[i] = Interval.top()
                case _:
                    raise NotImplementedError(f"Unsupported parameter type {p}")
    else:
        for i, x in enumerate(inputs.values):
            match x:
                case jpamb.case.Int(value=v):
                    locals[i] = Interval.alpha([StackInt(v)])
                case jpamb.case.Boolean(value=v):
                    locals[i] = Interval.alpha([StackInt(int(v))])
                case jpamb.case.Char(value=v):
                    locals[i] = Interval.alpha([StackInt(ord(v))])
                case _:
                    raise NotImplementedError(f"Unsupported value {x!r}")

    state = State(tuple(locals), ())
    return {PC(methodid, 0): state}


@dataclass
class AbstractInterpreter:
    bc: jpamb.Bytecode
    worklist: deque[PC]
    states: dict[PC, State]

    @staticmethod
    def initial(bc: jpamb.Bytecode, methodid: jvm.AbsMethodID, inputs):
        states = initialstate(bc, methodid, inputs)
        worklist = deque(states.keys())

        return AbstractInterpreter(bc, worklist, states)

    def step(self) -> tuple[PC, set[str]]:
        pc = self.worklist.pop()

        print(f"Stepping {pc}:\n > {self.bc[pc]}", file=sys.stderr)

        finals = set()

        for res in manystep(self.bc, pc, self.states[pc]):
            if isinstance(res, str):
                finals.add(res)
            else:
                pc_, st = res

                if pc_.offset <= pc.offset:
                    # A jump back to an earlier (or the same) instruction is
                    # reachable.  That is the only way an instruction can run
                    # twice, so only then can the method run forever.
                    finals.add("*")

                before = self.states.get(pc_, None)
                if before is None:
                    after = st
                else:
                    after = before | st
                if before is None or after != before:
                    self.states[pc_] = after
                    self.worklist.append(pc_)

        return pc, finals


def interpret():
    """The static analysis"""
    methodid, input, steps = jpamb.getcase(
        "static",
        "1.0",
        "The Rice Theorem Cookers",
        ["static", "python"],
        for_science=True,
    )
    suite, eff = jpamb.setup()
    bc = jpamb.Bytecode(suite, eff, {})

    ai = AbstractInterpreter.initial(bc, methodid, input)

    x = jpamb.emit_init(ai.states)

    while steps > 0 and ai.worklist:
        pc, final = ai.step()
        for f in final:
            jpamb.emit_step(x, pc, f, depth=1)
            steps -= 1

        x = jpamb.emit_step(x, pc, ai.states, depth=1)
        steps -= 1


def analyse():
    """The static analysis"""

    methodid = jpamb.getmethodid(
        "static",
        "1.0",
        "The Rice Theorem Cookers",
        ["static", "python"],
        for_science=True,
    )

    suite, eff = jpamb.setup()
    bc = jpamb.Bytecode(suite, eff, {})

    steps = 300

    final = set()
    try:
        ai = AbstractInterpreter.initial(bc, methodid, None)
        while steps > 0 and ai.worklist:
            _pc, finals = ai.step()
            final |= finals
            steps -= 1
    except NotImplementedError as e:
        # Something we cannot analyse yet: "maybe" is the only safe answer.
        print(f"Not analysed: {e}", file=sys.stderr)
        for f in jpamb.QUERIES:
            print(f"{f};maybe")
        return

    if ai.worklist:
        # TEMPORARY, until widening: we ran out of steps before reaching a
        # fixed point.  The states still on the worklist were never explored,
        # and they might lead to an error we have not seen.  "no" would be a
        # guess, so "maybe" is the only safe answer.
        print("Not analysed: no fixed point within the step limit", file=sys.stderr)
        for f in jpamb.QUERIES:
            print(f"{f};maybe")
        return

    for f in jpamb.QUERIES:
        if f not in final:
            print(f"{f};no")
        else:
            print(f"{f};maybe")
