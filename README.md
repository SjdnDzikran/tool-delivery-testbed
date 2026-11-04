# Tool Delivery Testbed

The Tool Delivery Testbed provides a Pi-based harness for comparing three ways to provide tools to AI agents: eager-loading MCP, deferred-loading MCP through Pi's native deferred exposure with tool search, and CLI plus progressively disclosed skills. Tasks cover information retrieval, browser operations, database operations, repository operations, and cross-family workflows.

The manifest-driven runner configures the model, tools, task, limits, and repetitions. Task verifiers inspect resulting artifacts or state. Review execution traces separately to determine whether an agent followed its assigned tool route.

## Tool delivery configurations

- **Eager-loading MCP:** MCP tools are exposed to the agent at the start of a task.
- **Deferred-loading MCP:** Pi's native tool-search flow lets the agent discover MCP tools when needed rather than exposing them as direct calls initially.
- **CLI plus progressively disclosed skills:** MCP is disabled; the agent uses command-line programs and can read relevant skill instructions as needed.

## Repository layout

- `measurements/testbed/common/` — shared verifier helpers and result format.
- `measurements/testbed/controls/` — two self-contained record-transformation tasks with fixtures and expected outputs.
- `measurements/testbed/composites/` — two cross-family tasks with database fixtures, setup/reset scripts, and independent verifiers.
- `measurements/testbed/gaia/` — GAIA-compatible answer verifier and synthetic regression fixtures.
- `measurements/testbed/rig/` — Pi runner, example manifests, capability setup scripts, CLI skills, tests, and optional Harbor integration.

See the [testbed guide](measurements/testbed/README.md), [runner guide](measurements/testbed/rig/README.md), and [runner reference](measurements/testbed/rig/GUIDE.md) for details.

## Requirements

- Python 3.11 or later for the runner and offline test suites.
- Pi 1.0.4 for Pi-based execution, with provider authentication configured locally.
- Optional capability installation: Linux x86_64, Node.js/npm versions specified by the committed lockfile, and the system tools listed in [`INSTALL.md`](measurements/testbed/rig/INSTALL.md).
- Optional Harbor execution: Docker/Compose and the dependencies described in [`harbor_pi/README.md`](measurements/testbed/rig/harbor_pi/README.md).

Offline task and runner tests use local fixtures and do not call model providers.

## Run the offline tests

From the repository root:

```bash
cd measurements/testbed
python3 controls/control_1_filter_sort/validation/run_tests.py
python3 controls/control_2_group_aggregate/validation/run_tests.py
python3 composites/composite_1_search_db/validation/run_tests.py
python3 composites/composite_2_db_repo/validation/run_tests.py
python3 gaia/validation/run_tests.py
```

Run the runner's offline tests separately:

```bash
cd measurements/testbed/rig
python3 -m unittest discover -s tests
python3 -m unittest verification.tests.test_canary_offline \
  verification.tests.test_capability_checks \
  verification.tests.test_recovery_e2e
```

Some optional Harbor tests require the Harbor runtime and additional dependencies.

## Plan a runner task

From `measurements/testbed/rig/`:

```bash
python3 runner.py validate examples/smoke.toml
python3 runner.py plan examples/smoke.toml
```

These commands validate and display a plan without invoking a model. Before live execution, configure a private provider-auth file and review the manifest, model identifier and settings, task setup/reset/verification commands, resource limits, and remote targets. `doctor` may contact configured tool servers. `runner.py run` invokes a model and can incur provider usage; some tasks can also modify databases or remote repositories.

Example manifests may depend on local paths, external task assets, services, or disposable accounts. Adapt and review them before use. Do not put credentials in manifests or task files.

## Task data and evaluation

The GAIA verifier accepts an operator-supplied task JSON. Its regression tests use synthetic fixtures. For benchmark use, obtain task records from the official source under its current access and license terms. Keep reference answers and verifier data outside the agent-visible workspace.

This repository includes task instructions, fixtures, expected outputs, and verifier code. For blind evaluation, prepare an agent workspace that contains only the materials intended for the agent, and keep reference outputs and verifiers in a separate trusted environment.

## Safety

The runner's configuration isolation does not enforce an OS security boundary. Same-user processes may access files outside the trial workspace, and containers do not provide complete isolation. Use disposable databases, browser profiles, and low-privilege accounts for tasks that can modify external state. Never point reset or cleanup scripts at personal or production resources.

Review task setup, reset, and cleanup code before running it. Check provider, dataset, and upstream software terms independently of this repository.

## License

Original testbed code and documentation are licensed under the [MIT License](LICENSE), except where a file or upstream dependency specifies different terms. The MIT License does not grant rights to third-party datasets, task content, provider APIs, or external software.
