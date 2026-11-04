# Optional capability installation

Most verifier and runner unit tests need only Python 3.11+. The capability installer is for Linux x86_64 and installs local dependencies for the optional Pi/Harbor experiments. It does not install Pi itself, provide credentials, provision remote tasks, or authorize a model run.

## Requirements

- Linux x86_64.
- Python 3.11+ (Harbor task images may use a separately pinned Python runtime).
- Node/npm matching the `packageManager` field and lockfile in `runtime/package.json` (currently npm 11.19.0).
- `curl`, `tar`, `sha256sum`, PostgreSQL client/server binaries, and Docker/Compose for the corresponding task modes.
- Provider and capability accounts only when using live services.

## Install pinned local capabilities

From the repository root:

```bash
measurements/testbed/rig/scripts/install-capabilities
. measurements/testbed/rig/env.sh
```

The installer checks downloaded release archives against pinned checksums, uses `npm ci` with the committed lockfile, and installs into the rig's local runtime tree. It is not a security audit; review current advisories and upstream release notes before enabling network-facing tools.

To start/stop the disposable PostgreSQL fixture, inspect the helper first and then use:

```bash
measurements/testbed/rig/scripts/pgfixture start
# Export the DSN printed by the helper only into the shell that needs it.
eval "$(measurements/testbed/rig/scripts/pgfixture env)"
measurements/testbed/rig/scripts/pgfixture stop
```

The fixture is for local test data, not a security boundary. Do not reuse it for valuable or production data.

## Credentials

No credential is stored in this repository. `env.sh` sets local executable paths and a separate GitHub CLI configuration directory but does not read token files or automatically import credentials. Export only the variables needed for the task, such as `BRAVE_API_KEY` and `STUDY_GITHUB_TOKEN`, in your private shell. Do not place values in TOML, JSON, task instructions, or version control.

For tasks that mutate GitHub, use a dedicated disposable account and a narrowly scoped token. Set `GITHUB_EVAL_ORG` and `TESTBED_GH_REPO` explicitly for the intended throwaway target. Verify the authenticated identity before allowing writes. Never use a personal or production account with reset/cleanup scripts.

Pi model authentication is referenced through `auth_source` in a local manifest. Change the sample path to a private auth file that you control. Do not copy an auth file into the repository or a task workspace.

## Live execution is opt-in

`runner.py validate`, `plan`, and the offline tests do not call a model. `doctor` may contact configured servers. `runner.py run` and Harbor's execution commands can consume model usage and may mutate external state. Read the manifest and relevant task code first, use low limits, and run only against disposable resources.

See [`README.md`](README.md) for the harness and [`harbor_pi/README.md`](harbor_pi/README.md) for the optional Harbor adapter. Historical package pins are provided for reproducibility, not as a recommendation to run unreviewed or outdated software.
