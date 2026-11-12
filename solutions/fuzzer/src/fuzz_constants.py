"""Stand-in for Tier 0: the int and string constants pushed anywhere in a class."""

from mutators import Dictionary


def class_constants(suite, eff, classname) -> Dictionary:
    ints, strings = set(), set()
    for method in suite.findclass(classname, eff=eff)["methods"]:
        for op in (method.get("code") or {}).get("bytecode", []):
            value = op["value"] if op["opr"] == "push" else None
            if value is not None:
                if value["type"] == "integer":
                    ints.add(value["value"])
                elif value["type"] == "string":
                    strings.add(value["value"])
    return Dictionary(tuple(sorted(ints)), tuple(sorted(strings)))