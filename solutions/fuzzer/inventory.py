import collections
import glob
import json

ops, invokes, gets, casts = (collections.Counter() for _ in range(4))
for path in glob.glob("target/decompiled/jpamb/cases/*.json"):
    for method in json.load(open(path))["methods"]:
        for ins in (method.get("code") or {}).get("bytecode", []):
            opr = ins["opr"]
            ops[opr] += 1
            if opr == "invoke":
                ref = ins["method"]["ref"]
                cls = ref.get("name", str(ref))
                invokes[f'{ins["access"]} {cls}.{ins["method"]["name"]}'] += 1
            elif opr == "get":
                gets[f'{ins["field"]["class"]}.{ins["field"]["name"]}'] += 1
            elif opr == "cast":
                casts[f'{ins["from"]} -> {ins["to"]}'] += 1

for title, counter in [("opr", ops), ("invoke", invokes), ("get", gets), ("cast", casts)]:
    print(f"== {title}")
    for key, n in counter.most_common():
        print(f"{n:5}  {key}")
