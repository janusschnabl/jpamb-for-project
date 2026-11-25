"""Expressions over a method's parameters, rebuilt from bytecode."""

from dataclasses import dataclass

import jpamb
import jvm


@dataclass(frozen=True)
class Param:
    index: int


@dataclass(frozen=True)
class Const:
    value: int


@dataclass(frozen=True)
class BinOp:
    op: str  # "+", "-" or "*"
    left: "Expr"
    right: "Expr"


Expr = Param | Const | BinOp

OPS = {jvm.BinaryOpr.Add: "+", jvm.BinaryOpr.Sub: "-", jvm.BinaryOpr.Mul: "*"}


def render(expr: Expr, names: list[str]) -> str:
    """Java source text for `expr`."""
    match expr:
        case Param(i):
            return names[i]
        case Const(c):
            return str(c)
        case BinOp(op, left, right):
            return f"({render(left, names)} {op} {render(right, names)})"


def unmodified_parameter(bc: jpamb.Bytecode, method: jvm.AbsMethodID, i: int) -> bool:
    """Local `i` is a parameter that is never written to."""
    if i >= len(method.extension.params):
        return False
    for op in bc.getmethod(method).opcodes:
        match op:
            case jvm.Store(index=j) | jvm.Incr(index=j) if j == i:
                return False
    return True


def stack_effect(op: jvm.Opcode) -> tuple[int, int] | None:
    """(pops, pushes), or None for instructions we don't model."""
    match op:
        case jvm.Push() | jvm.Load():
            return 0, 1
        case jvm.Binary():
            return 2, 1
        case jvm.Negate() | jvm.Cast():
            return 1, 1
    return None


def expression_at(bc: jpamb.Bytecode, pc, depth: int) -> Expr | None:
    """The value at stack position `depth` just before `pc`, or None."""
    method = pc.method
    opcodes = bc.getmethod(method).opcodes
    targets = {
        op.target for op in opcodes
        if isinstance(op, (jvm.Goto, jvm.If, jvm.Ifz))
    }

    def value(j: int, depth: int) -> Expr | None:
        # the value at `depth` just before index j
        while True:
            if j == 0 or j in targets:
                return None
            j -= 1
            op = opcodes[j]
            if depth > 0:
                effect = stack_effect(op)
                if effect is None:
                    return None
                pops, pushes = effect
                depth = depth - pushes + pops
                continue
            match op:
                case jvm.Push(type=jvm.Int(), value=c):
                    return Const(c)
                case jvm.Load(type=jvm.Int(), index=i):
                    return Param(i) if unmodified_parameter(bc, method, i) else None
                case jvm.Binary(type=jvm.Int(), operant=o) if o in OPS:
                    left, right = value(j, 1), value(j, 0)
                    if left is None or right is None:
                        return None
                    return BinOp(OPS[o], left, right)
                case jvm.Negate(type=jvm.Int()):
                    inner = value(j, 0)
                    return None if inner is None else BinOp("-", Const(0), inner)
            return None

    return value(pc.offset, depth)
