# Harbor/Pi adapter

This directory contains an optional adapter that runs Pi agents inside Harbor-managed task environments and verifies artifacts separately. It supplements the native runner; it is not required for the offline verifier suites.

## Components

- `adapter.py` — Pi-backed Harbor agent and trial configuration.
- `bridge.py` — control-task preparation and readiness checks.
- `pilot.py` — bounded task preparation and explicit execution entry points.
- `actual_tasks.py` / `actual_verify.py` — adapters for externally provisioned task assets.
- `pilot_image/` and `actual_verifier/` — container build inputs and verifier dependencies.
- `test_*.py` — offline unit and integration tests using fakes.

## Important constraints

- A live run requires Docker/Compose, pinned runtime images, model authentication, and any capability-specific credentials or task services.
- Review the selected manifest and all setup, reset, verifier, and cleanup code before execution. Some task modes may create or modify remote GitHub repositories or local database/browser state.
- Live model runs can spend provider usage. Use explicit, bounded, disposable accounts and inspect token/time caps first.
- The code separates the verifier/reference data from the agent workspace for supported tasks, but containers and per-user accounts are not a complete security boundary.
- Record validation against the exact code, runtime image, task assets, and configuration used.

Installation guidance is in [`../INSTALL.md`](../INSTALL.md). Runner behavior and known isolation limits are in [`../GUIDE.md`](../GUIDE.md).
