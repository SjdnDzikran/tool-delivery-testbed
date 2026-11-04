# Capability smoke: GitHub read

Use the available GitHub capability to read the configured repository's default
branch commit SHA. The target is supplied through `TESTBED_GH_REPO`.

Write the full, 40-character SHA followed by a newline to `artifacts/github.txt`.
Do not change the repository, branches, files, issues, or pull requests.
Then stop.
