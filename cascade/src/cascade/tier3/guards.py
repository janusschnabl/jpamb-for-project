"""Turn Tier 1 alarms into guards on the method's parameters."""

from dataclasses import dataclass

import jpamb
import jvm

from cascade.tier1 import Alarm, Ref
from cascade.tier1.analysis import origin

# stack position of the faulting value (0 = top of stack)
FAULT_DEPTH = {
    jvm.Binary: 0,      # [..., dividend, divisor]
    jvm.ArrayLoad: 0,   # [..., array, index]
    jvm.ArrayStore: 1,  # [..., array, index, value]
}


def parameter_at(bc: jpamb.Bytecode, alarm: Alarm, depth: int) -> int | None:
    """Index of the parameter at stack position `depth`, or None."""
    match origin(bc, alarm.pc, depth):
        case ("local", i):
            pass
        case _:
            return None

    method = alarm.pc.method
    if i >= len(method.extension.params):
        return None

    # the parameter must still hold its original value
    for op in bc.getmethod(method).opcodes:
        match op:
            case jvm.Store(index=j) | jvm.Incr(index=j) if j == i:
                return None
    return i


def faulting_parameter(bc: jpamb.Bytecode, alarm: Alarm) -> int | None:
    """Index of the parameter that is the faulting value, or None."""
    depth = FAULT_DEPTH.get(type(alarm.instruction))
    if depth is None:
        return None
    return parameter_at(bc, alarm, depth)


@dataclass(frozen=True)
class Guard:
    """Reject inputs where parameter `param` causes `error`.

    For out of bounds, the array is either parameter `array` or has the
    constant length `length`.
    """

    method: jvm.AbsMethodID
    param: int
    error: str
    array: int | None = None
    length: int | None = None

    def condition(self, names: list[str]) -> str:
        """Java condition that is true for the bad inputs."""
        p = names[self.param]
        if self.error == "divide by zero":
            return f"{p} == 0"
        if self.array is not None:
            a = names[self.array]
            return f"{a} != null && ({p} < 0 || {p} >= {a}.length)"
        return f"{p} < 0 || {p} >= {self.length}"


def guard_for(bc: jpamb.Bytecode, alarm: Alarm) -> Guard | None:
    """A guard for the alarm, or None if we can't build one."""
    param = faulting_parameter(bc, alarm)
    if param is None:
        return None
    method = alarm.pc.method

    if alarm.error == "divide by zero":
        return Guard(method, param, alarm.error)

    if alarm.error == "out of bounds":
        depth = FAULT_DEPTH[type(alarm.instruction)] + 1  # array is below the index
        array = parameter_at(bc, alarm, depth)
        if array is not None:
            return Guard(method, param, alarm.error, array=array)
        ref = alarm.state.stack[-1 - depth]
        if isinstance(ref, Ref) and ref.length.min == ref.length.max:
            return Guard(method, param, alarm.error, length=ref.length.min)

    return None


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
            guard = guard_for(bc, alarm)
            if guard is not None and guard not in guards:
                guards.append(guard)
    return guards
