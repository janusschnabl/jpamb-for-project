# Tier 1: interval analysis (AI-generated!)

This folder is **Tier 1** of our cascade: a sound static analysis that proves
errors **impossible**.

If you build Tier 0, 2 or 3, this is the file to read. It explains what Tier 1
gives you, how to call it, and what it cannot do.

## Where it fits

```
  query (method, error)
        │
  Tier 0  syntactic analyses     "no"  if the faulting instruction is not there
        │   → constants K
  Tier 1  interval analysis      "no"  if no input can cause the error     ← this folder
        │   → alarms: the instructions it could not prove safe, with the intervals there
  Tier 2  coverage fuzzing       "yes" if it finds an input that causes the error
        │   → the inputs it tried
  Tier 3  guard synthesis        a verified guard for what is still undecided
```

Tier 1 can only ever answer **"no"**. A "no" is a proof: the error cannot
happen for any input. Everything else is "maybe", and for every "maybe" error
Tier 1 tells you **where** it could not prove safety. That is what the later
tiers work on.

## Quick start

All commands run from the JPAMB folder (the repository root).

**Analyse one method** (the JPAMB format, one line per query):

```bash
uv run --with-editable cascade tier1-intervals "jpamb.cases.Simple.divideByN:(I)I"
```

```
*;no
assertion error;no
divide by zero;maybe
null pointer;no
ok;maybe
out of bounds;no
```

The alarms are printed to stderr, so they show up in the terminal but not in
the JPAMB answer.

**Score it on all of JPAMB:**

```bash
uv run --with-editable cascade jpamb analyse -N 1 tier1-intervals
```

**Run the tests** of the abstract domain:

```bash
uv run --with-editable cascade --with pytest --with hypothesis python -m pytest cascade/tests/test_tier1_domain.py -q
```

## Use it from your own code

```python
from cascade.tier1 import analyse_method

result = analyse_method("jpamb.cases.Simple.divideByN:(I)I")

result.verdicts                      # {"divide by zero": "maybe", "ok": "maybe", "null pointer": "no", ...}
result.proven("null pointer")        # True: proven impossible
result.unproven("divide by zero")    # [Alarm(...)]: where it could happen
```

Run your script with `uv run --with-editable cascade python your_script.py`
so that `cascade` can be imported.

`analyse_method` also accepts a `jvm.AbsMethodID`, and an existing
`jpamb.Bytecode` as a second argument if you already have one, and the
constants `K` from Tier 0 as a third (see below).

### `Result`

| Field | Type | Meaning |
| :-- | :-- | :-- |
| `verdicts` | `dict[str, str]` | for each JPAMB query: `"no"` (proven impossible) or `"maybe"` |
| `alarms` | tuple of `Alarm` | every instruction where an error could not be ruled out |
| `analysed` | `bool` | `False` if the method uses something Tier 1 cannot handle; then every verdict is `"maybe"` |
| `reason` | `str` or `None` | why it was not analysed |
| `states` | `dict[PC, State]` | the full result: the abstract state before every reachable instruction |

### `Alarm`

| Field | Meaning |
| :-- | :-- |
| `error` | `"divide by zero"`, `"out of bounds"`, `"null pointer"` or `"assertion error"` |
| `pc` | the instruction; `pc.offset` is its index in the method's bytecode |
| `instruction` | the instruction itself, e.g. `binary:I div` |
| `line` | the Java source line |
| `state` | the abstract state right **before** the instruction |

A `state` has `locals` and `stack`. Each entry is an `Interval` (an int, with
`.min` and `.max`) or a `Ref` (an array, with `.null` and `.length` - which is given as an inverval).

### Example

```
analyse_method("jpamb.cases.Simple.divideByN:(I)I")

verdicts:  divide by zero: maybe,  ok: maybe,  everything else: no
alarm:     divide by zero at `binary:I div`, pc 2, line 46
           stack before it: [1, 1], [-2147483648, 2147483647]
                                    └ the divisor: any int, so 0 is possible
```

## What each tier can do with it

**Tier 0 → Tier 1.** Tier 1 widens with thresholds (`∇K`), and takes Tier 0's
constant dictionary `K` as an argument:

```python
from cascade.tier0.constant_mining import extract_constants

K = extract_constants(bc.getmethod(methodid).opcodes)
result = analyse_method(methodid, bc, constants=K)
```

Without `constants`, Tier 1 collects the same constants itself, so it also
works on its own. `constants=set()` turns thresholds off (plain widening).

**Tier 1 → Tier 2 (fuzzing).**
- Skip every query whose verdict is `"no"`. It is proven impossible, so no
  input can trigger it and fuzzing for it is wasted time.
- Aim at the alarms. Their `pc`s are the only instructions worth reaching,
  so coverage feedback can focus on the branches that lead to them.

**Tier 1 → Tier 3 (guards).**
- `alarm.line` is where in the Java source the guard belongs.
- `alarm.state` says which values reach the instruction:

  | Instruction | Where the values are |
  | :-- | :-- |
  | division (`binary:I div` / `rem`) | divisor = `state.stack[-1]` |
  | `array_load` | index = `state.stack[-1]`, array = `state.stack[-2]` |
  | `array_store` | value = `stack[-1]`, index = `stack[-2]`, array = `stack[-3]` |

- After patching, run `analyse_method` on the patched method: if the alarm is
  gone, the guard is verified.

## How it works (short version)

- **Intervals.** Every int is described by its smallest and largest possible
  value, `[min, max]`, within the range of a 32-bit int. Arithmetic follows the
  JVM, including overflow: if a result can wrap around, it becomes "any int".
- **One state per instruction.** The analysis keeps, for every instruction, the
  intervals of all locals and stack values, and updates them until nothing
  changes (a *fixed point*). Where paths meet, intervals are joined.
- **Widening with thresholds (`∇K`).** At the start of a loop, a bound that
  keeps growing jumps to the next constant of the method (the set `K`), and
  past the last one to the int limit, so every loop stabilises. There is no
  step limit: the result covers every execution, however long. For
  `for (i = 0; i != 8; i++)`, `i` stops at `[0, 8]` instead of `[0, INT_MAX]`,
  which is what proves `arrayFillUntilEqual` in bounds.
- **Branches.** After `if (i < 8)`, each branch knows more about `i`, and that
  knowledge is written back to the variable (`origin` and `backtrack` in
  `analysis.py`). This is what proves loops like `for (i = 0; i < a.length; i++) a[i]`
  in bounds.
- **Arrays.** An array is described by whether it may be null and the interval
  of its length. Its contents are not tracked.
- **Calls.** A called method is analysed with the actual argument values. A
  recursive call (a method calling itself) is not followed: there, Tier 1
  assumes anything can happen.

The code, in this folder: `interval.py` holds the domain (`Interval`, `Ref`),
`lattice.py` the lecturer's interfaces and law checkers, `analysis.py` the
analysis with one `case` per bytecode instruction in `manystep`.

## Results

On all 80 JPAMB cases (55 methods, including our own cases):
**207** outcomes proven impossible and **no wrong answers**. Without
thresholds it is 206; the difference is `arrayFillUntilEqual`.

## Questions

Ask Bastian. If you need something from Tier 1 that is not here, say so early:
changing what `analyse_method` returns is easy now and harder later.
