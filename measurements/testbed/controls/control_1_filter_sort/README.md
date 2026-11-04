# Control 1: filter and sort

A self-contained deterministic transformation over the records in `instruction.md`.

## Task

Select records where `department == "Engineering"` and `salary >= 90000`. Sort by salary descending, then by name ascending. Write `result.json` as a JSON array of `{id, name, salary}` objects.

The task is intentionally solvable with native file/computation tools and does not require an external capability. The verifier checks the output artifact only; route activations are audited separately.

## Files

- `instruction.md` — agent-facing prompt and records.
- `fixtures/records.json` — generated input records.
- `gen_records.py` — deterministic fixture and instruction generator.
- `ref_solve.py` — reference solution generator.
- `expected/result.json` — verifier-only reference fixture; do not copy into an agent workspace.
- `verify.py` — task verifier.
- `validation/run_tests.py` — offline verifier regression tests.

## Commands

```bash
python3 validation/run_tests.py
python3 verify.py --artifacts /path/to/artifacts
```

To regenerate the task fixture and its expected answer:

```bash
python3 gen_records.py
python3 ref_solve.py
```

This task is a constructed test fixture, not a measured study result.
