import jpamb
import jvm
from jpamb.case import Input, Int

from executor import run

suite, eff = jpamb.setup()
bc = jpamb.Bytecode(suite, eff, {})
DIVIDE = jvm.AbsMethodID.decode("jpamb.cases.Simple.divideByN:(I)I")

def test_error_outcome_and_coverage():
    r = run(bc, DIVIDE, Input((Int(0),)))
    assert r.outcome == "divide by zero"
    assert r.failure is None
    assert r.steps == 3
    assert len(r.coverage) == 3

def test_normal_outcome():
    assert run(bc, DIVIDE, Input((Int(1),))).outcome == "ok"

def test_interpreter_failure_is_reported_not_raised():
    r = run(bc, DIVIDE, Input(())) # Argument is missing
    assert r.outcome is None
    assert r.failure is not None

def test_deterministic():
    assert run(bc, DIVIDE, Input((Int(7),))) == run(bc, DIVIDE, Input((Int(7),)))