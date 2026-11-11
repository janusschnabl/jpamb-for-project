"""A silent concrete interpreter for the JPAMB bytecode subset."""

from javaint import java_div, java_rem, to_i32, to_u16, to_i16

import jpamb
import jvm
import jvm.state as jvmc

MAX_ARRAY_SIZE = 100_000


def binary(op, a: int, b: int) -> int | str:
    match op:
        case jvm.BinaryOpr.Add:
            return to_i32(a + b)
        case jvm.BinaryOpr.Sub:
            return to_i32(a - b)
        case jvm.BinaryOpr.Mul:
            return to_i32(a * b)
        case jvm.BinaryOpr.Div:
            return "divide by zero" if b == 0 else java_div(a, b)
        case jvm.BinaryOpr.Rem:
            return "divide by zero" if b == 0 else java_rem(a, b)
        case _:
            raise NotImplementedError(f"Unhandled binary {op!r}")


def compare(op, a: int, b: int) -> bool:
    match op:
        case jvm.CmpOpr.Eq:
            return a == b
        case jvm.CmpOpr.Ne:
            return a != b
        case jvm.CmpOpr.Lt:
            return a < b
        case jvm.CmpOpr.Le:
            return a <= b
        case jvm.CmpOpr.Gt:
            return a > b
        case jvm.CmpOpr.Ge:
            return a >= b
        case _:
            raise NotImplementedError(f"Unhandled comparison {op!r}")


def step(bc: jpamb.Bytecode, state: jvmc.State) -> tuple[jvmc.PC, jvmc.State | str]:
    """Execute one instruction. Returns the pc it ran at, and the new state
    or a final outcome string."""
    frame = state.frames.peek()
    pc = frame.pc
    opr = bc[pc]
    output = state

    match opr:
        case jvm.Push(type=jvm.Int(), value=v):
            frame.stack.push(jvmc.StackInt(v))
            frame.pc += 1

        case jvm.Push(type=jvm.Reference()):
            frame.stack.push(jvmc.StackReference(0))  # null
            frame.pc += 1

        case jvm.Load(index=n):
            frame.stack.push(frame.locals[n])
            frame.pc += 1

        case jvm.Store(index=n):
            frame.locals[n] = frame.stack.pop()
            frame.pc += 1

        case jvm.Dup(words=1):
            v = frame.stack.pop()
            frame.stack.push(v)
            frame.stack.push(v)
            frame.pc += 1

        case jvm.Incr(index=n, amount=amount):
            v = frame.locals[n]
            frame.locals[n] = jvmc.StackInt(to_i32(v.value + amount))
            frame.pc += 1

        case jvm.Negate(type=jvm.Int()):
            v = frame.stack.pop()
            frame.stack.push(jvmc.StackInt(to_i32(-v.value)))
            frame.pc += 1

        case jvm.Binary(type=jvm.Int(), operant=op):
            b = frame.stack.pop()
            a = frame.stack.pop()
            result = binary(op, a.value, b.value)
            if isinstance(result, str):
                output = result
            else:
                frame.stack.push(jvmc.StackInt(result))
                frame.pc += 1

        case jvm.Goto(target=target):
            frame.pc %= target

        case jvm.Ifz(condition=op, target=target):
            v = frame.stack.pop()
            if compare(op, v.value, 0):
                frame.pc %= target
            else:
                frame.pc += 1

        case jvm.If(condition=op, target=target):
            b = frame.stack.pop()
            a = frame.stack.pop()
            if compare(op, a.value, b.value):
                frame.pc %= target
            else:
                frame.pc += 1

        case jvm.Get(static=True, field=field):
            # We never run class setup code, so assertions are always enabled.
            assert field.extension.name == "$assertionsDisabled", field
            frame.stack.push(jvmc.StackInt(0))
            frame.pc += 1

        case jvm.New(classname=cn):
            ref = state.heap.new(jvmc.HeapObject(cn, {}))
            frame.stack.push(ref)
            frame.pc += 1

        case jvm.InvokeSpecial(method=m) if m.extension.name == "<init>":
            # Constructors do nothing in our subset. Pop the receiver and arguments.
            for _ in range(len(m.extension.params) + 1):
                frame.stack.pop()
            frame.pc += 1

        case jvm.Throw():
            ref = frame.stack.pop()
            if ref.value == 0:
                output = "null pointer"
            else:
                obj = state.heap[ref]
                if obj.classname == jvm.ClassName("java.lang.AssertionError"):
                    output = "assertion error"
                else:
                    raise NotImplementedError(f"Cannot throw {obj!r}")

        case jvm.Return(type=t):
            value = None if t is None else frame.stack.pop()
            state.frames.pop()
            if state.frames:
                caller = state.frames.peek()
                if value is not None:
                    caller.stack.push(value)
                caller.pc += 1
            else:
                output = "ok"

        case jvm.NewArray(type=t, dim=1):
            size = frame.stack.pop().value
            if size < 0 or size > MAX_ARRAY_SIZE:
                raise NotImplementedError(f"array size {size} is not modelled")
            ref = state.heap.new(jvmc.HeapArray(t, [0] * size))
            frame.stack.push(ref)
            frame.pc += 1

        case jvm.ArrayLength():
            ref = frame.stack.pop()
            if ref.value == 0:
                output = "null pointer"
            else:
                frame.stack.push(jvmc.StackInt(len(state.heap[ref].values)))
                frame.pc += 1

        case jvm.ArrayLoad(type=jvm.Int() | jvm.Char()):
            index = frame.stack.pop().value
            ref = frame.stack.pop()
            if ref.value == 0:
                output = "null pointer"
            else:
                values = state.heap[ref].values
                if 0 <= index < len(values):
                    frame.stack.push(jvmc.StackInt(values[index]))
                    frame.pc += 1
                else:
                    output = "out of bounds"

        case jvm.ArrayStore(type=t) if isinstance(t, (jvm.Int, jvm.Char)):
            value = frame.stack.pop().value
            index = frame.stack.pop().value
            ref = frame.stack.pop()
            if ref.value == 0:
                output = "null pointer"
            else:
                values = state.heap[ref].values
                if 0 <= index < len(values):
                    values[index] = to_u16(value) if isinstance(t, jvm.Char) else value
                    frame.pc += 1
                else:
                    output = "out of bounds"

        case jvm.InvokeStatic(method=m):
            callee = jvmc.Frame.from_method(bc.getmethod(m))
            for i in reversed(range(len(m.extension.params))):
                callee.locals[i] = frame.stack.pop()
            state.frames.push(callee)

        case jvm.Push(type=jvm.Object(), value=v):
            frame.stack.push(state.heap.new(jvmc.HeapString(v)))
            frame.pc += 1

        case jvm.InvokeVirtual(method=m) if (
            m.classname == jvm.ClassName("java.lang.String")
            and m.extension.name == "equals"
        ):
            arg = frame.stack.pop()
            receiver = frame.stack.pop()
            if receiver.value == 0:
                output = "null pointer"
            else:
                this = state.heap[receiver]
                other = None if arg.value == 0 else state.heap[arg]
                equal = isinstance(other, jvmc.HeapString) and other.content == this.content
                frame.stack.push(jvmc.StackInt(1 if equal else 0))
                frame.pc += 1

        case jvm.Cast(from_=jvm.Int(), to_=jvm.Short()):
            v = frame.stack.pop()
            frame.stack.push(jvmc.StackInt(to_i16(v.value)))
            frame.pc += 1

        case jvm.Cast(from_=jvm.Int(), to_=jvm.Char()):
            v = frame.stack.pop()
            frame.stack.push(jvmc.StackInt(to_u16(v.value)))
            frame.pc += 1

        case _:
            raise NotImplementedError(opr.help())

    return pc, output


def initial(bc: jpamb.Bytecode, methodid: jvm.AbsMethodID, input: jpamb.Input):
    """Build the starting state: the method's first frame with the arguments in
    its local variables."""
    frame = jvmc.Frame.from_method(bc.getmethod(methodid))
    state = jvmc.State(jvmc.Heap(), jvmc.CallStack.from_frames([frame]))
    for i, v in enumerate(input.values):
        match v:
            case jpamb.case.Boolean(value):
                frame.locals[i] = jvmc.StackInt(1 if value else 0)
            case jpamb.case.Int(value):
                frame.locals[i] = jvmc.StackInt(value)
            case jpamb.case.Char(value):
                frame.locals[i] = jvmc.StackInt(ord(value))
            case jpamb.case.Array(contains=jvm.Int(), values=values):
                frame.locals[i] = state.heap.new(jvmc.HeapArray(jvm.Int(), list(values)))
            case jpamb.case.Array(contains=jvm.Char(), values=values):
                frame.locals[i] = state.heap.new(
                    jvmc.HeapArray(jvm.Char(), [ord(c) for c in values])
                )
            case jpamb.case.String(value):
                frame.locals[i] = state.heap.new(jvmc.HeapString(value))
            case _:
                raise NotImplementedError(f"Cannot convert input value {v!r}")
    return state


def execute(bc, methodid, input, max_steps: int = 1000) -> str:
    """Run one input to completion and return the outcome. '*' means the step
    limit was hit."""
    state = initial(bc, methodid, input)
    for _ in range(max_steps):
        _, state = step(bc, state)
        if isinstance(state, str):
            return state
    return "*"