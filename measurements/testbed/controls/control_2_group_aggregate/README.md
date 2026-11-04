# Control 2: group and aggregate

A self-contained deterministic group-and-aggregate task over the same input records as Control 1.

## Task

Group records by region and report each region's headcount, total salary, and average salary. Write `result.json` as an object keyed by region in alphabetical order. `avg_salary` is a JSON number rounded to two decimal places using the half-away-from-zero convention stated in `instruction.md`.

The task is intentionally solvable with native file/computation tools and does not require an external capability. The verifier checks the output artifact only; route activations are audited separately.

## Files

- `instruction.md` — agent-facing prompt and records.
- `fixtures/records.json` — generated input records.
- `gen_records.py` — deterministic fixture and instruction generator.
- `ref_solve.py` — reference solution generator using decimal arithmetic.
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
