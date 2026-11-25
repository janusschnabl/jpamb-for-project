"""Turn Tier 1 alarms into guards on the method's parameters."""

import contextlib
import io
from dataclasses import dataclass

import jpamb
import jvm

from cascade.tier1 import Alarm, Ref, analyse_method
from cascade.tier1.analysis import origin
from cascade.tier3.expr import (
    Expr,
    evaluate,
    expression_at,
    parameters,
    render,
    substitute,
    unmodified_parameter,
)

MAX_CALL_DEPTH = 3

# stack position of the faulting value (0 = top of stack)
FAULT_DEPTH = {
    jvm.Binary: 0,      # [..., dividend, divisor]
    jvm.ArrayLoad: 0,   # [..., array, index]
    jvm.ArrayStore: 1,  # [..., array, index, value]
}


def parameter_at(bc: jpamb.Bytecode, pc, depth: int) -> int | None:
    """Index of the parameter at stack position `depth` before `pc`, or None."""
    match origin(bc, pc, depth):
        case ("local", i) if unmodified_parameter(bc, pc.method, i):
            return i
    return None


@dataclass(frozen=True)
class Guard:
    """Reject inputs where `value` causes `error`.

    For out of bounds, the array is either parameter `array` or has the
    constant length `length`.
    """

    method: jvm.AbsMethodID
    value: Expr
    error: str
    array: int | None = None
    length: int | None = None
    moved: bool = False  # moved here from a callee

    def condition(self, names: list[str]) -> str:
        """Java condition that is true for the bad inputs."""
        v = render(self.value, names)
        if self.error == "divide by zero":
            return f"{v} == 0"
        if self.array is not None:
            a = names[self.array]
            return f"{a} != null && ({v} < 0 || {v} >= {a}.length)"
        return f"{v} < 0 || {v} >= {self.length}"

    def rejects(self, inp: jpamb.Input) -> bool:
        """`condition` evaluated on a concrete input (keep the two in sync)."""
        args = [v.value if hasattr(v, "value") else v for v in inp.values]
        v = evaluate(self.value, args)
        if self.error == "divide by zero":
            return v == 0
        if self.array is not None:
            return v < 0 or v >= len(inp.values[self.array].values)
        return v < 0 or v >= self.length


def guard_for(bc: jpamb.Bytecode, alarm: Alarm) -> Guard | None:
    """A guard for the alarm, or None if we can't build one."""
    depth = FAULT_DEPTH.get(type(alarm.instruction))
    if depth is None:
        return None
    value = expression_at(bc, alarm.pc, depth)
    if value is None or not parameters(value):
        return None
    method = alarm.pc.method

    if alarm.error == "divide by zero":
        return Guard(method, value, alarm.error)

    if alarm.error == "out of bounds":
        depth += 1  # the array is below the index
        array = parameter_at(bc, alarm.pc, depth)
        if array is not None:
            return Guard(method, value, alarm.error, array=array)
        ref = alarm.state.stack[-1 - depth]
        if isinstance(ref, Ref) and ref.length.min == ref.length.max:
            return Guard(method, value, alarm.error, length=ref.length.min)

    return None


def guards_for(bc: jpamb.Bytecode, alarm: Alarm, depth: int = MAX_CALL_DEPTH) -> list[Guard]:
    """Guards for the alarm; for a call, the callee's guards moved to the caller."""
    if isinstance(alarm.instruction, jvm.InvokeStatic):
        return call_guards(bc, alarm, depth) if depth > 0 else []
    guard = guard_for(bc, alarm)
    return [] if guard is None else [guard]


def call_guards(bc: jpamb.Bytecode, alarm: Alarm, depth: int) -> list[Guard]:
    callee = alarm.instruction.method
    n = len(callee.extension.params)
    # the last argument is on top of the stack
    args = [expression_at(bc, alarm.pc, n - 1 - i) for i in range(n)]
    arrays = [parameter_at(bc, alarm.pc, n - 1 - i) for i in range(n)]

    with contextlib.redirect_stderr(io.StringIO()):
        inner = analyse_method(callee, bc)

    guards = []
    for inner_alarm in inner.unproven(alarm.error):
        for g in guards_for(bc, inner_alarm, depth - 1):
            if any(args[i] is None for i in parameters(g.value)):
                continue
            array = None
            if g.array is not None:
                array = arrays[g.array]
                if array is None:
                    continue
            moved = Guard(
                alarm.pc.method, substitute(g.value, args), g.error, array, g.length, moved=True
            )
            if moved not in guards:
                guards.append(moved)
    return guards


GUARDABLE = ("divide by zero", "out of bounds")


def candidates(bc: jpamb.Bytecode, result: "CascadeResult") -> list[Guard]:
    """Guards for the guardable errors the cascade did not prove impossible."""
    if result.tier1 is None:
        return []
    guards = []
    for error in GUARDABLE:
        if result.verdicts[error].answer == "no":
            continue
        for alarm in result.tier1.unproven(error):
            for guard in guards_for(bc, alarm):
                if guard not in guards:
                    guards.append(guard)
    return guards


def over_rejections(guard: Guard, observed: list) -> list:
    """Observed (input, outcome) pairs the guard rejects that did not end in its error."""
    return [
        (inp, outcome)
        for inp, outcome in observed
        if guard.rejects(inp) and outcome != guard.error
    ]
