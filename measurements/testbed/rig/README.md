# Pi experiment runner

The runner is a Python 3.11+ manifest-driven harness for comparing tool-delivery routes in a pinned Pi environment. It supports eager MCP, deferred MCP through native tool search, and CLI plus explicitly selected skills.

## Safe offline commands

Run from this directory:

```bash
python3 runner.py validate examples/smoke.toml
python3 runner.py plan examples/smoke.toml
python3 -m unittest discover -s tests
python3 -m unittest verification.tests.test_canary_offline \
  verification.tests.test_capability_checks \
  verification.tests.test_recovery_e2e
```

The listed unit tests use local fakes/fixtures and do not invoke a model provider. `verification/tests/test_supervise_main.py` and the Harbor adapter tests additionally require the optional Harbor runtime. `doctor` can contact configured MCP servers, so inspect its manifest and environment first.

## Runner commands

```bash
python3 runner.py validate MANIFEST.toml
python3 runner.py plan MANIFEST.toml
python3 runner.py doctor MANIFEST.toml
python3 runner.py status MANIFEST.toml
python3 runner.py run MANIFEST.toml
python3 runner.py run --resume MANIFEST.toml
```

`run` invokes a model and can consume paid or subscription usage. Review the manifest, model ID/settings, token limits, task setup/reset/verify commands, credential scope, and remote targets before running. `trial` is an ad-hoc path; consult `python3 runner.py trial --help` before use.

The runner freezes a manifest and seeded trial plan into a digest-checked campaign record, uses per-trial directories, and preserves completed attempts. Read [`GUIDE.md`](GUIDE.md) for the schema and semantics. Default output is local to the user profile; do not commit generated run data.

## Directory map

- `runner.py` — native runner.
- `examples/` — manifests and task materials. Some are historical research configurations or require external inputs; they are not all turnkey.
- `harbor_pi/` — optional Harbor/Pi adapter, task setup, orchestration, and its offline tests.
- `skills/` — example CLI skills used by manifests.
- `instances/` — sample Pi model and MCP settings.
- `runtime/` — pinned dependency manifests. Installed binaries and mutable environments are excluded from version control.
- `verification/` — offline utilities and tests for capability routes and runner behavior.

## Installation and limitations

See [`INSTALL.md`](INSTALL.md) for optional pinned capability installation. Harbor setup and actual external tasks require their own runtime, accounts, and task fixtures. Do not supply a personal or production account to reset scripts.

Configuration isolation is not an OS sandbox: same-user processes may access files outside the trial workspace. A verifier pass alone does not establish route compliance; inspect the recorded trace independently. Public example source and fixtures may expose answers, so never use this checkout as the agent's workspace for a blind evaluation.
