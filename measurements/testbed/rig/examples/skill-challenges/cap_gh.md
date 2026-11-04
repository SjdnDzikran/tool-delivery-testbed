# Typed GraphQL read

Use the configured GitHub CLI and supplied `TESTBED_GH_REPO` to read the
repository. Use the GitHub GraphQL API, not REST endpoints, for this answer.
Do not change any repository objects or authentication configuration.

Query `repository.nameWithOwner` and its `defaultBranchRef`:

- branch `name`;
- the target Commit's `oid`;
- `parents.nodes.oid`, with the parent connection limited to one using a GraphQL
  variable declared as a non-null integer. Supply that integer through the CLI's
  typed field mechanism, not by interpolating a literal into the query.

Save the unfiltered JSON response, including its top-level `data` object, to
`artifacts/github.json`. Do not synthesize a response from remembered commits.
Then stop.
