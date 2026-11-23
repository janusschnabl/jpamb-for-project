"""Turn Tier 1 alarms into guards on the method's parameters."""

from dataclasses import dataclass

import jpamb
import jvm

from cascade.tier1 import Alarm
from cascade.tier1.analysis import origin

# stack position of the faulting value (0 = top of stack)
FAULT_DEPTH = {
    jvm.Binary: 0,      # [..., dividend, divisor]
    jvm.ArrayLoad: 0,   # [..., array, index]
    jvm.ArrayStore: 1,  # [..., array, index, value]
}


def faulting_parameter(bc: jpamb.Bytecode, alarm: Alarm) -> int | None:
    """Index of the parameter that is the faulting value, or None."""
    depth = FAULT_DEPTH.get(type(alarm.instruction))
    if depth is None:
        return None

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


@dataclass(frozen=True)
class Guard:
    """Reject inputs where parameter `param` causes `error`."""

    method: jvm.AbsMethodID
    param: int
    error: str

    def condition(self, name: str) -> str:
        """Java condition that is true for the bad inputs."""
        return f"{name} == 0"


def guard_for(bc: jpamb.Bytecode, alarm: Alarm) -> Guard | None:
    """A guard for a divide-by-zero alarm, or None if we can't build one."""
    if alarm.error != "divide by zero":
        return None
    param = faulting_parameter(bc, alarm)
    if param is None:
        return None
    return Guard(alarm.pc.method, param, alarm.error)
