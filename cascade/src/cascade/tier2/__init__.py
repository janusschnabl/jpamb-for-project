"""Tier 2: coverage-guided fuzzing of what Tiers 0 and 1 could not rule out.

from cascade.tier2 import run_tier2

cascade = Cascade()
result = cascade.run("jpamb.cases.Simple.divideByN:(I)I")
tier2 = run_tier2(cascade.bc, result)
tier2.answers["divide by zero"]     "yes"
tier2.witnesses["divide by zero"]   the input that causes it
"""

from .fuzzing import Tier2Result, run_tier2
