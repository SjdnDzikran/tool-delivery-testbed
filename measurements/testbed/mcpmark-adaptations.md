# Upstream task adaptation note

The runner can host MCPMark's `release_management_workflow` task. This repository does not redistribute the upstream task or verifier; obtain the source from [`eval-sys/mcpmark`](https://github.com/eval-sys/mcpmark) at the recorded source revision and comply with its Apache-2.0 license and task-data terms.

The source task was recorded at commit `cd45b7f57923b9b3985467f5139927575f83141c`. Its repository-state fixture is pinned separately in the runner at `mcpmark-source/harmony`, commit `f348e7689f5f0599b7cfef7de6d6a597a57615c`.

The local instruction adaptation makes the final release state explicit: open a pull request from `release-v1.1.0` into `main`, use a title containing `Release v1.1.0`, squash-merge it, and keep the branch. The upstream verifier is not modified. Verify the precise task instructions and upstream revision before using this adapter in another study.

This file documents source provenance and an instruction adaptation only. It includes no run records or outcome data.
