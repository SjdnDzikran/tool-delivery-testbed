Produce a canary echo of the exact text `ping` using the canary capability
provided in this environment, and record the output.

- This workspace is provisioned with exactly one canary capability: it is
  either an MCP tool (declared directly, or discoverable with the
  `tool_search` tool when present) or a CLI program named `canary-cli`
  documented by the `canary-skill` skill.
- Find the canary capability, invoke its echo operation once with the text
  `ping`, and take the output line that starts with `CANARY_ECHO_OK:`.
- Create a file `result.txt` in your current working directory containing
  exactly that line and nothing else.

Do not modify any other file.
