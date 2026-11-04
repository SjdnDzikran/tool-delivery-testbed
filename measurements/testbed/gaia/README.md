# GAIA-compatible verifier

`verify_gaia.py` checks a task answer, source quote, and optional transcript evidence using a task JSON supplied at runtime. The regression suite uses synthetic fixtures. For benchmark use, obtain task records from the official source under its current access and license terms.

## Task input

Supply an authorized task file outside the agent-visible workspace with the required fields:

```json
{
  "task_id": "operator-supplied-id",
  "question": "Operator-supplied task question",
  "reference_answer": "Verifier-only answer",
  "provenance": {}
}
```

The verifier reads `question` only as task metadata; it evaluates `reference_answer`. Keep this file and the verifier out of the agent workspace. Obtain benchmark records from the official source under its current access and license terms; do not use an unofficial mirror as a substitute for source verification.

## Run

From the repository root:

```bash
python3 measurements/testbed/gaia/verify_gaia.py \
  --artifacts /path/to/private/artifacts \
  --task /path/to/authorized-task.json \
  --transcript /path/to/private/session.jsonl
```

The transcript flag is optional. Without it, route-evidence checking is marked skipped. The verifier exit codes follow `../common/verify_lib.py` (0 pass, 1 incorrect, 2 incomplete, 3 missing artifact, 4 verifier error).

## Synthetic regression tests

The `validation/fixtures/` data is synthetic and exists only to test verifier behavior. Run from `measurements/testbed/`:

```bash
python3 gaia/validation/run_tests.py
```

The suite runs entirely against the synthetic fixtures and does not contact the benchmark source.
