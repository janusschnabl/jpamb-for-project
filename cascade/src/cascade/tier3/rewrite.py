"""Insert guards into the Java source."""

import difflib
from collections import defaultdict
from pathlib import Path

import jpamb

from cascade.tier3.guards import Guard
from cascade.tier3.source import find_method, parameter_names


def guard_statement(guard: Guard, names: list[str], indent: str) -> str:
    return (
        f"{indent}if ({guard.condition(names)}) {{\n"
        f'{indent}  throw new IllegalArgumentException("{guard.error}");\n'
        f"{indent}}}\n"
    )


def insertion(suite: jpamb.Suite, guard: Guard) -> tuple[int, str] | None:
    """(byte offset, text) to insert the guard at, or None if not possible."""
    method = find_method(suite, guard.method)
    if method is None:
        return None
    statements = method.child_by_field_name("body").named_children
    if not statements:
        return None
    first = statements[0]
    line_start = first.start_byte - first.start_point.column
    indent = " " * first.start_point.column
    return line_start, guard_statement(guard, parameter_names(method), indent)


def rewrite(suite: jpamb.Suite, guards: list[Guard]) -> dict[Path, str]:
    """Patched source text for every file that gets at least one guard."""
    by_file = defaultdict(list)
    for guard in guards:
        if (ins := insertion(suite, guard)) is not None:
            by_file[suite.sourcefile(guard.method.classname)].append(ins)

    patched = {}
    for path, inserts in by_file.items():
        source = path.read_bytes()
        # bottom-up, so earlier offsets stay valid
        for offset, text in sorted(inserts, reverse=True):
            source = source[:offset] + text.encode() + source[offset:]
        patched[path] = source.decode()
    return patched


def diff(path: Path, new_text: str) -> str:
    old = path.read_text().splitlines(keepends=True)
    new = new_text.splitlines(keepends=True)
    return "".join(difflib.unified_diff(old, new, str(path), str(path) + " (guarded)"))
