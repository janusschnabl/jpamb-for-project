"""Run Tier 3 on every static method of the case classes and report the numbers.

    PYTHONPATH=cascade/src:solutions/fuzzer/src uv run python -m cascade.tier3.run
"""

import collections
import contextlib
import io
import sys

from cascade.pipeline import Cascade
from cascade.tier3.compile import compile_sources, output_folder, write_patched
from cascade.tier3.guards import GUARDABLE, candidates, over_rejections
from cascade.tier3.rewrite import diff, rewrite


def case_methods(cascade: Cascade):
    """Every static method with bytecode in the jpamb.cases classes."""
    for mid, mjson in sorted(cascade.program.methods.items(), key=lambda kv: str(kv[0])):
        if (
            mid.classname.dotted().startswith("jpamb.cases.")
            and "static" in mjson["access"]
            and mjson.get("code") is not None
            and not mid.extension.name.startswith("<")
        ):
            yield mid


def main():
    cascade = Cascade()
    suite, eff = cascade.bc.suite, cascade.bc.eff
    counts = collections.Counter()
    kept = []

    for mid in case_methods(cascade):
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                result = cascade.run(mid, fuzz=True)
                guards = candidates(cascade.bc, result)
        except Exception as e:
            counts["methods failed"] += 1
            print(f"failed {mid}: {e}", file=sys.stderr)
            continue
        counts["methods"] += 1
        for error in GUARDABLE:
            if result.verdicts[error].answer != "no":
                counts[f"{error}: not proven safe"] += 1

        observed = result.tier2.fuzz.observed if result.tier2 and result.tier2.fuzz else []
        for g in guards:
            kind = "outer" if g.moved else "inner"
            if over_rejections(g, observed):
                counts[f"{g.error}: dropped ({kind})"] += 1
                status = "DROP"
            else:
                counts[f"{g.error}: kept ({kind})"] += 1
                kept.append(g)
                status = "KEEP"
            print(f"{status} {kind:5} {g.error:15} {mid}")

    patched = rewrite(suite, kept)
    out = output_folder(suite, eff)
    ok, log = compile_sources(suite, eff, write_patched(suite, patched, out), out)
    (out / "guards.diff").write_text("".join(diff(p, t) for p, t in patched.items()))

    print()
    for key in sorted(counts):
        print(f"{key:40} {counts[key]}")
    print(f"{'guards written':40} {len(kept)} in {len(patched)} files")
    print(f"{'patched sources compile':40} {ok}")
    print(f"diff: {out / 'guards.diff'}")
    if not ok:
        print(log)


if __name__ == "__main__":
    main()
