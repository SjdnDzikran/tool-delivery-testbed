# Supplying GAIA task files

The task-staging helper reads exactly two operator-supplied JSON files from this directory. Each file needs `task_id`, `question`, `reference_answer`, and `provenance` fields. Keep reference answers in verifier-only storage and show only the question to the agent. The directory's `.gitignore` prevents local task files from being committed.

Obtain records from the official benchmark source under its current access and license terms. Record the source revision and provenance outside the agent-visible workspace. Do not rely on an unofficial mirror or redistribute gated task content.

See [`../README.md`](../README.md) for the verifier command and synthetic offline tests.
