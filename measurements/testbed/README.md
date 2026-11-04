# Testbed source

This directory contains task definitions, fixtures, verifiers, and the execution rig for the Tool Delivery Testbed.

## Components

- `common/` — shared answer matching and machine-readable verifier outcomes.
- `controls/` — two self-contained, tool-free record-transformation controls.
- `composites/` — two constructed cross-family tasks with database fixtures and independent verification.
- `gaia/` — a verifier interface and synthetic regression fixtures. Actual GAIA records and answers are supplied separately by an authorized operator.
- `rig/` — Pi runner, optional Harbor integration, configuration examples, skills, and offline tests.

For blind evaluation, place only agent-facing instructions and task inputs in the agent workspace. Keep reference data and verifiers in a separate trusted environment.

## Verifier contract

Verifiers are written for Python 3 and report a machine-readable JSON result. The shared exit-code contract in `common/verify_lib.py` is:

| Code | Meaning |
|---:|---|
| 0 | Pass |
| 1 | Incorrect answer or state |
| 2 | Incomplete artifact |
| 3 | Missing artifact |
| 4 | Verifier or invocation error |

Each task's own README or verifier help gives its required artifacts and dependencies. Run the validation suites from the repository root using the commands in the top-level README. Those suites use local fixtures and do not call model providers.

## Blind evaluation

Task instructions, fixtures, expected outputs, and verifiers are visible in this tree. Prepare a separate agent workspace and keep reference outputs and verification code out of it when evaluating blind tasks.
