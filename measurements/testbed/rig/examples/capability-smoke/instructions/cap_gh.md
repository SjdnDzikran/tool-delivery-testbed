# Capability smoke: GitHub

Look up the configured GitHub repository in `TESTBED_GH_REPO` (read-only; do
not modify anything). Create `artifacts/repo.json` with exactly two keys:

- `"nameWithOwner"`: the repository's owner/name
- `"description"`: the repository description exactly as GitHub reports it
  (use `null` if GitHub reports no description)

Then stop.
