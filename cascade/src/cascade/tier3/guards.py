"""Turn Tier 1 alarms into guards on the method's parameters."""

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
