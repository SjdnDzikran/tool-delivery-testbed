# Composite tasks

Two constructed tasks chain capability families. Each task has a versioned synthetic database fixture, an instruction, a restore script, an independent verifier, and an offline validation suite. The search task asks for a public biographical fact; it is not a wholly synthetic data task.

| Task | Chain | Main checks |
|---|---|---|
| `composite_1_search_db/` | Web search → PostgreSQL | A source/evidence artifact and one matching row in the task database |
| `composite_2_db_repo/` | PostgreSQL → GitHub repository | A recomputed database answer and a precisely formatted file on the configured repository's default branch |

The task instructions describe the expected artifact names and required actions without embedding the reference SQL or verifier logic. Verifiers are route-neutral: they inspect the resulting evidence/state and do not invoke MCP servers or CLI skills.

## Local validation

From `measurements/testbed/`:

```bash
python3 composites/composite_1_search_db/validation/run_tests.py
python3 composites/composite_2_db_repo/validation/run_tests.py
```

These tests use stubs and disposable local fixtures; they do not contact GitHub, a model provider, or a live search service.

## External state and safety

`composite_1_search_db/restore.sh` drops and recreates its configured database schema. `composite_2_db_repo/restore.sh` may delete the task file from the configured repository when the required environment variables are present. Set explicit disposable targets only after reading each script. Do not use personal or production resources.

The database and repository names are supplied through environment variables. Credentials are not included. These two tasks are constructed examples rather than official benchmark tasks.
