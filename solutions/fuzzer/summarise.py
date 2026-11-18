"""Summarise the experiment CSV: how often each variant finds the listed errors,
and where the variants differ."""

import argparse
import csv
from collections import defaultdict
from pathlib import Path
from statistics import median


def load(path):
    with open(path, newline="") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:  # The CSV holds only text: turn it back into values
        row["found"] = row["found"] == "True"
        row["first_execution"] = (
            int(row["first_execution"]) if row["first_execution"] else None
        )
        row["interpreter_failures"] = int(row["interpreter_failures"])
    return rows


def short(method):
    return method.removeprefix("jpamb.cases.")


def cell(rows):
    """'found/seeds', plus the median executions to the first witness."""
    hits = [r for r in rows if r["found"]]
    text = f"{len(hits)}/{len(rows)}"
    if hits:
        text += f" (median {median([r['first_execution'] for r in hits]):.0f})"
    return text


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "csv",
        type=Path,
        nargs="?",
        default=Path("solutions/fuzzer/results/experiment.csv"),
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="show every method and error, not only where variants differ",
    )
    args = parser.parse_args()

    rows = load(args.csv)
    variants = list(
        dict.fromkeys(r["variant"] for r in rows)
    )  # In order of first appearance

    print("Errors found, per variant (one row = one listed error on one seed)")
    for variant in variants:
        mine = [r for r in rows if r["variant"] == variant]
        found = sum(r["found"] for r in mine)
        print(
            f"  {variant:18} {found:5} / {len(mine):<5} {100 * found / len(mine):5.1f}%"
        )
    broken = sum(1 for r in rows if r["interpreter_failures"] > 0)
    print(f"  rows where the interpreter failed at least once: {broken}")

    cells = defaultdict(lambda: defaultdict(list))  # (method, error) -> variant -> rows
    for r in rows:
        cells[(r["method"], r["error"])][r["variant"]].append(r)

    never, differing, same = [], [], 0
    for key, by_variant in sorted(cells.items()):
        counts = {v: sum(r["found"] for r in by_variant[v]) for v in variants}
        if sum(counts.values()) == 0:
            never.append(key)
        elif len(set(counts.values())) > 1:
            differing.append(key)
        else:
            same += 1

    shown = sorted(cells) if args.all else differing
    print(
        f"\n{len(cells)} (method, error) pairs: {same} found equally often by every "
        f"variant, {len(differing)} differ, {len(never)} never found"
    )

    if shown:
        label = {key: f"{short(key[0])} : {key[1]}" for key in shown}
        width = max(len(text) for text in label.values())
        print("\n" + " " * width + "  " + "  ".join(f"{v:>26}" for v in variants))
        for key in shown:
            print(
                f"{label[key]:<{width}}  "
                + "  ".join(f"{cell(cells[key][v]):>26}" for v in variants)
            )

    if never:
        print("\nNever found by any variant:")
        for method, error in never:
            print(f"  {short(method)} : {error}")


if __name__ == "__main__":
    main()
