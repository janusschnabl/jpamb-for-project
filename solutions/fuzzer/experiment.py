"""Switch-off experiment: run the fuzzer in several variants on many seeds.

Writes one CSV row per (variant, method, error, seed)."""

import argparse
import csv
import os
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from fuzz_constants import class_constants
from fuzzer import fuzz
from mutators import Dictionary, MutationConfig

import jpamb
import jvm
from jpamb.case import Case

ERRORS = {"divide by zero", "assertion error", "out of bounds", "null pointer"}
PROGRESS_SECONDS = 30

# name -> (use the constants?, use coverage feedback?, mutator switches)
VARIANTS = {
    "full": (True, True, MutationConfig()),
    "no-dictionary": (False, True, MutationConfig()),
    "no-guidance": (True, False, MutationConfig()),
    "no-resize-bursts": (
        True,
        True,
        MutationConfig(resize=False, burst_probability=0.0),
    ),
    "ints-only": (True, True, MutationConfig()),
}

COLUMNS = [
    "variant",
    "method",
    "seed",
    "error",
    "found",
    "first_execution",
    "executions",
    "corpus_size",
    "interpreter_failures",
    "seconds",
]

_state = {}  # Filled in once per worker process by _init


def _init():
    suite, eff = jpamb.setup()
    _state["suite"], _state["eff"] = suite, eff
    _state["bc"] = jpamb.Bytecode(suite, eff, {})
    _state["constants"] = {}  # class name -> Dictionary, so we mine each class once


def _dictionary(methodid):
    cache = _state["constants"]
    key = methodid.classname.encode()
    if key not in cache:
        cache[key] = class_constants(_state["suite"], _state["eff"], methodid.classname)
    return cache[key]


def _job(job):
    variant, method_text, errors, seed, budget = job
    use_constants, guided, config = VARIANTS[variant]
    methodid = jvm.AbsMethodID.decode(method_text)
    dictionary = _dictionary(methodid) if use_constants else Dictionary()
    if variant == "ints-only":
        dictionary = Dictionary(ints=dictionary.ints)

    started = time.perf_counter()
    result = fuzz(
        _state["bc"], methodid, budget, seed, dictionary, guided=guided, config=config
    )
    seconds = round(time.perf_counter() - started, 2)

    rows = []
    for error in errors:
        witness = result.witnesses.get(error)  # None if this error was not found
        rows.append(
            {
                "variant": variant,
                "method": method_text,
                "seed": seed,
                "error": error,
                "found": witness is not None,
                "first_execution": "" if witness is None else witness.execution,
                "executions": result.executions,
                "corpus_size": result.corpus_size,
                "interpreter_failures": sum(result.failures.values()),
                "seconds": seconds,
            }
        )
    return rows


def _methods(extras, include_sheet=True):
    """{method text: set of listed errors}: from the answer sheet (unless skipped), plus --extra."""
    methods = {}
    if include_sheet:
        lines = Path("target/stats/cases.txt").read_text().splitlines()
        cases = [Case.decode(line) for line in lines if line.strip()]
        for methodid, method_cases in Case.by_entry(cases):
            expected = {c.result for c in method_cases} & ERRORS
            if expected:
                methods[methodid.encode()] = expected
    for extra in extras:
        method_text, _, error = extra.rpartition("=")
        if error not in ERRORS:
            raise SystemExit(
                f"--extra {extra!r}: error must be one of {sorted(ERRORS)}"
            )
        methods.setdefault(method_text, set()).add(error)
    return methods


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--budget", type=int, default=1000)
    parser.add_argument("--seeds", type=int, default=10, help="seeds 0 .. N-1")
    parser.add_argument(
        "--variants", nargs="+", choices=list(VARIANTS), default=list(VARIANTS)
    )
    parser.add_argument("--extra", action="append", default=[], metavar="METHOD=ERROR")
    parser.add_argument(
        "--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1)
    )
    parser.add_argument(
        "--out", type=Path, default=Path("solutions/fuzzer/results/experiment.csv")
    )
    parser.add_argument(
        "--only-extra",
        action="store_true",
        help="skip the answer-sheet methods, run only the --extra ones",
    )
    parser.add_argument(
        "--match",
        nargs="+",
        metavar="TEXT",
        help="only run methods whose id contains any of these texts",
    )
    args = parser.parse_args()

    methods = _methods(args.extra, include_sheet=not args.only_extra)
    if args.match:
        methods = {
            text: errors
            for text, errors in methods.items()
            if any(m in text for m in args.match)
        }
    jobs = [
        (variant, text, tuple(sorted(errors)), seed, args.budget)
        for variant in args.variants
        for text, errors in sorted(methods.items())
        for seed in range(args.seeds)
    ]
    print(f"{len(jobs)} jobs on {args.workers} workers -> {args.out}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    started = last_print = time.perf_counter()
    with (
        open(args.out, "w", newline="") as handle,
        ProcessPoolExecutor(args.workers, initializer=_init) as pool,
    ):
        writer = csv.DictWriter(handle, COLUMNS)
        writer.writeheader()
        futures = [pool.submit(_job, job) for job in jobs]
        for done, future in enumerate(as_completed(futures), 1):
            writer.writerows(future.result())
            handle.flush()
            now = time.perf_counter()
            if now - last_print >= PROGRESS_SECONDS or done == len(jobs):
                print(f"  {done}/{len(jobs)} jobs, {now - started:.0f}s elapsed")
                last_print = now


if __name__ == "__main__":
    main()
