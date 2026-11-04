---
name: gh
description: Use when inspecting or changing GitHub repositories, pull requests, issues, releases, or Actions runs.
---

# GitHub

Use `gh-github` with the supplied study credentials and `$TESTBED_GH_REPO`
(`OWNER/REPO`). Stop on missing target or authentication failure; leave login
configuration unchanged. Run `gh-github COMMAND [SUBCOMMAND] --help` for unfamiliar options.

- For `pr`, `issue`, `release`, `run`, or `workflow`, select `-R "$TESTBED_GH_REPO"`. Inspect with `pr list`,
  `pr view N`, `pr diff N`, `issue list`, or `run list`.
  Use `--json FIELDS --jq FILTER` where supported.
- Clone with `gh-github repo clone "$TESTBED_GH_REPO"`; use `git` for local history and edits.
  Local files are not published: stage with `git add FILES`, commit with
  `git commit -m MESSAGE`, then `git push origin HEAD:BRANCH` to the intended branch.
  Confirm the remote file with `gh-github api "repos/$TESTBED_GH_REPO/contents/PATH?ref=BRANCH"`.
- REST: `gh-github api "repos/$TESTBED_GH_REPO/PATH"`. Quote endpoints containing
  query strings; use `--paginate` for complete collections (`--slurp` combines pages).
- API fields: `-f key=value` sends strings; `-F key=value` converts types and accepts
  `@FILE`. Fields default the method to POST; use `--method GET` for query parameters.
- Create PRs noninteractively with `pr create --base BASE --head BRANCH --title TITLE
  --body-file FILE`. Merge or delete only when requested, using the required merge strategy.
- Read back changed objects. Before claiming a merge, confirm `pr view N --json state`
  reports `MERGED`; a successful merge command can merely enable auto-merge or enqueue the PR.
