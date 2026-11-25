"""Tier 1: the unbounded interval analysis (an abstract interpreter over JVM bytecode)."""

import sys
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass

from .interval import INT_MAX, Interval, Ref

import jpamb
import sexpr
from jpamb import jvm
from jvm.state import PC, StackInt


def type_range(t: jvm.Type) -> Interval | None:
    """All the values a JVM type allows, as an interval.

    boolean, char, short and byte are stored as ints on the JVM, but with a
    smaller range.  Returns None for types that are not int-like (arrays,
    objects, long, double, ...)."""
    match t:
        case jvm.Boolean():
            return Interval(0, 1)
        case jvm.Char():
            return Interval(0, 65535)
        case jvm.Short():
            return Interval(-(2**15), 2**15 - 1)
        case jvm.Byte():
            return Interval(-(2**7), 2**7 - 1)
        case jvm.Int():
            return Interval.top()
        case _:
            return None


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

    def widen(self, other, K=()):

        return State(
            tuple(s1.widen(s2, K) for s1, s2 in zip(self.locals, other.locals)),
            tuple(s1.widen(s2, K) for s1, s2 in zip(self.stack, other.stack)),
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

def jump_targets(opcodes) -> set[int]:
    targets = set()
    for op in opcodes:
        match op:
            case jvm.Goto(target=t) | jvm.If(target=t) | jvm.Ifz(target=t):
                targets.add(t)
    return targets


def origin(bc: jpamb.Bytecode, pc: PC, depth: int = 0):
    opcodes = bc.getmethod(pc.method).opcodes
    targets = jump_targets(opcodes)
    j = pc.offset
    while True:
        if j == 0 or j in targets:
            return None
        j -= 1
        match opcodes[j]:
            case jvm.Load(index=i):
                if depth == 0:
                    return ("local", i)
                depth -= 1
            case jvm.Push():
                if depth == 0:
                    return None
                depth -= 1
            case jvm.ArrayLength():
                if depth == 0:
                    match origin(bc, pc % j, 0):
                        case ("local", i):
                            return ("len", i)
                    return None
            case _:
                return None


def backtrack(state: State, org, value: Interval) -> State:
    match org:
        case ("local", i):
            return state.store(i, value)
        case ("len", i):
            ref = state.load(i)
            return state.store(i, Ref(ref.null, ref.length & value))
        case _:
            return state


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
            org = origin(bc, pc)

            if split.if_true.possible:
                yield (pc % target, backtrack(after, org, split.if_true.left))
            if split.if_false.possible:
                yield (pc + 1, backtrack(after, org, split.if_false.left))
                
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

        case jvm.ArrayStore(type=t):
            [ref, index, _], after = state.pop(3)

            if ref.null:
                yield "null pointer"

            if index.min < 0 or index.max >= ref.length.min:
                yield "out of bounds"

            possible = index & Interval(0, ref.length.max - 1)
            if not possible.is_bot:
                yield (pc + 1, after)
                
        case jvm.Store(index=i):
            [val], after = state.pop(1)
            yield (pc + 1, after.store(i, val))

        case jvm.Goto(target=t):
            yield (pc % t, state)

        case jvm.InvokeStatic(method=m):
            n = len(m.extension.params)
            if n > 0:
                args, after = state.pop(n)
            else:
                args, after = (), state

            outcomes, result = call(bc, m, args)

            for outcome in outcomes:
                if outcome != "ok":
                    yield outcome

            if "ok" in outcomes:
                if m.extension.return_type is None:
                    yield (pc + 1, after)
                elif result is not None:
                    yield (pc + 1, after.push(result))
            
        case jvm.ArrayLength():
            [ref], after = state.pop()
            
            if ref.null:
                yield "null pointer"
            
            if not ref.length.is_bot:
                yield (pc + 1, after.push(ref.length))
        
        case jvm.If(condition=op, target=target):
            [v1, v2], after = state.pop(2)
            split = v1.compare(v2, op)
            org1 = origin(bc, pc, 1)
            org2 = origin(bc, pc, 0)

            if split.if_true.possible:
                st = backtrack(after, org1, split.if_true.left)
                st = backtrack(st, org2, split.if_true.right)
                yield (pc % target, st)
            if split.if_false.possible:
                st = backtrack(after, org1, split.if_false.left)
                st = backtrack(st, org2, split.if_false.right)
                yield (pc + 1, st)
                
        case jvm.ArrayLoad(type=t):
            [ref, index], after = state.pop(2)
            
            if ref.null:
                yield "null pointer"
            
            allowed_indices = ref.length.min - 1

            if not index <= Interval(0, allowed_indices):
                yield "out of bounds"

            possible = index & Interval(0, ref.length.max - 1)
            if not possible.is_bot:
                yield (pc + 1, after.push(type_range(t)))

        case jvm.Incr(index=i, amount=c):
            local_val = state.load(i)
            result, _ = local_val.arithmetic(Interval(c, c), jvm.BinaryOpr.Add)
            yield (pc + 1, state.store(i, result))
            
        case jvm.Push(type=jvm.Int(), value=v):
            val = Interval.alpha([StackInt(v)])
            yield (pc + 1, state.push(val))
            
        case jvm.Push(type=jvm.Reference()):
            yield (pc + 1, state.push(Ref(null=True, length=Interval.bot())))      
        
        case jvm.Negate():
            [val], after = state.pop(1)
            negated, _ = Interval(0, 0).arithmetic(val, jvm.BinaryOpr.Sub)
            yield (pc + 1, after.push(negated))
            
        case jvm.Cast(from_=jvm.Int(), to_=to):
            range = type_range(to)
            if range is None:
                raise NotImplementedError(f"Unsupported cast to {to}")

            [val], after = state.pop(1)

            if val <= range:
                casted = val
            else:
                casted = range

            yield (pc + 1, after.push(casted))
            
        case jvm.Binary(operant=op):
            [v1, v2], after = state.pop(2)
            result, errors = v1.arithmetic(v2, op)
            yield from errors
            if not result.is_bot:
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

ACTIVE: list[jvm.AbsMethodID] = []

def unknown_call(m: jvm.AbsMethodID):
    outcomes = {"assertion error", "divide by zero", "null pointer", "out of bounds", "*", "ok"}
    ret = m.extension.return_type
    if ret is None:
        return outcomes, None
    if (range := type_range(ret)) is not None:
        return outcomes, range
    if isinstance(ret, (jvm.Array, jvm.Object)):
        return outcomes, Ref(null=True, length=Interval(0, INT_MAX))
    raise NotImplementedError(f"Unsupported return type {ret}")


def call(bc: jpamb.Bytecode, m: jvm.AbsMethodID, args):
    if m in ACTIVE:
        return unknown_call(m)

    try:
        method = bc.getmethod(m)
    except Exception:
        return unknown_call(m)


    locals = [Interval.bot()] * method.max_locals
    for i, arg in enumerate(args):
        locals[i] = arg
    start = PC(m, 0)
    ai = AbstractInterpreter(
        bc, deque([start]), {start: State(tuple(locals), ())}, loop_heads(bc, m), frozenset(method_constants(bc, m))
    )

    ACTIVE.append(m)
    try:
        outcomes = set()
        while ai.worklist:
            _pc, finals = ai.step()
            outcomes |= finals
    except NotImplementedError:
        return unknown_call(m)
    finally:
        ACTIVE.pop()

    result = None
    for pc, state in ai.states.items():
        match bc[pc]:
            case jvm.Return(type=t) if t is not None:
                value = state.stack[-1]
                result = value if result is None else result | value
    return outcomes, result


def method_constants(bc: jpamb.Bytecode, methodid: jvm.AbsMethodID) -> set[int]:
    constants = set()
    for op in bc.getmethod(methodid).opcodes:
        match op:
            case jvm.Push(type=jvm.Int(), value=int(v)):
                constants.add(v)
            case jvm.Incr(amount=c):
                constants.add(c)
            case jvm.Ifz():
                constants.add(0)
    return constants


def loop_heads(bc: jpamb.Bytecode, methodid: jvm.AbsMethodID) -> set[int]:
    heads = set()
    for i, op in enumerate(bc.getmethod(methodid).opcodes):
        match op:
            case jvm.Goto(target=t) | jvm.If(target=t) | jvm.Ifz(target=t):
                if t <= i:
                    heads.add(t)
    return heads

def initialstate(
    bc: jpamb.Bytecode,
    methodid: jvm.AbsMethodID,
    inputs: jpamb.Input | None,
) -> dict[PC, State]:
    method = bc.getmethod(methodid)
    locals = [Interval.bot()] * method.max_locals

    if inputs is None:
        for i, p in enumerate(methodid.extension.params):
            range = type_range(p)
            if range is not None:
                locals[i] = range
            elif isinstance(p, jvm.Array) and type_range(p.contains) is not None:
                locals[i] = Ref(null=False, length=Interval(0, INT_MAX))
            else:
                raise NotImplementedError(f"Unsupported parameter type {p}")
    else:
        for i, x in enumerate(inputs.values):
            match x:
                case jpamb.case.Array(values=values):
                    n = len(values)
                    locals[i] = Ref(null=False, length=Interval(n, n))
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
    heads: set[int]  # the loop heads: where we widen instead of join
    K: frozenset[int] = frozenset()  # the widening thresholds

    @staticmethod
    def initial(bc: jpamb.Bytecode, methodid: jvm.AbsMethodID, inputs, constants=None):
        states = initialstate(bc, methodid, inputs)
        worklist = deque(states.keys())
        if constants is None:
            constants = method_constants(bc, methodid)

        return AbstractInterpreter(bc, worklist, states, loop_heads(bc, methodid), frozenset(constants))

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
                    finals.add("*")

                before = self.states.get(pc_, None)
                if before is None:
                    after = st
                elif pc_.offset in self.heads:
                    after = before.widen(before | st, self.K)
                else:
                    after = before | st
                if before is None or after != before:
                    self.states[pc_] = after
                    self.worklist.append(pc_)

        return pc, finals

ERRORS = ("assertion error", "divide by zero", "null pointer", "out of bounds")

@dataclass(frozen=True)
class Alarm:
    pc: PC
    error: str
    instruction: jvm.Opcode
    line: int | None
    state: State

    def __str__(self):
        return f"{self.error} at {self.instruction} (line {self.line}): {self.state}"


@dataclass(frozen=True)
class Result:
    methodid: jvm.AbsMethodID
    analysed: bool
    verdicts: dict[str, str]
    alarms: tuple[Alarm, ...]
    states: dict[PC, State] 
    reason: str | None = None

    def proven(self, query: str) -> bool:
        return self.verdicts[query] == "no"

    def unproven(self, error: str | None = None) -> list[Alarm]:
        return [a for a in self.alarms if error is None or a.error == error]


def source_lines(bc: jpamb.Bytecode, methodid: jvm.AbsMethodID) -> list[tuple[int, int]]:
    method = bc.suite.findmethod(methodid, eff=bc.eff)
    return sorted((entry["offset"], entry["line"]) for entry in method["code"]["lines"])


def line_of(lines: list[tuple[int, int]], offset: int) -> int | None:
    found = None
    for start, line in lines:
        if start <= offset:
            found = line
    return found


def analyse_method(
    methodid: str | jvm.AbsMethodID,
    bc: jpamb.Bytecode | None = None,
    constants: set[int] | None = None,
) -> Result:
    if isinstance(methodid, str):
        methodid = jpamb.parse_methodid(methodid)
    if bc is None:
        suite, eff = jpamb.setup()
        bc = jpamb.Bytecode(suite, eff, {})

    final = set()
    try:
        ai = AbstractInterpreter.initial(bc, methodid, None, constants)
        while ai.worklist:
            _pc, finals = ai.step()
            final |= finals
    except NotImplementedError as e:
        return Result(
            methodid,
            analysed=False,
            verdicts={q: "maybe" for q in jpamb.QUERIES},
            alarms=(),
            states={},
            reason=str(e),
        )

    lines = source_lines(bc, methodid)
    alarms = []
    for pc, state in sorted(ai.states.items(), key=lambda item: item[0].offset):
        for res in manystep(bc, pc, state):
            if res in ERRORS:
                alarms.append(Alarm(pc, res, bc[pc], line_of(lines, pc.offset), state))

    return Result(
        methodid,
        analysed=True,
        verdicts={q: "maybe" if q in final else "no" for q in jpamb.QUERIES},
        alarms=tuple(alarms),
        states=dict(ai.states),
    )


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

    result = analyse_method(methodid)

    if not result.analysed:
        print(f"Not analysed: {result.reason}", file=sys.stderr)
    for alarm in result.alarms:
        print(f"Alarm: {alarm}", file=sys.stderr)

    for f in jpamb.QUERIES:
        print(f"{f};{result.verdicts[f]}")
