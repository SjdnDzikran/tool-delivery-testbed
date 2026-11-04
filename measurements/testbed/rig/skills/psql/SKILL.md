---
name: psql
description: Use when inspecting schemas, querying data, or modifying a PostgreSQL database.
---

# PostgreSQL

Connect only to the supplied task database:

```bash
psql -X -w -v ON_ERROR_STOP=1 "${TESTBED_PG_DSN:?}" -c 'SQL'
```

- `-X` skips startup files; `-w` prevents password prompts; `ON_ERROR_STOP=1`
  makes SQL errors fail the script. Keep stderr visible and check exit status.
- Discover schema with `-c '\dn'`, `-c '\dt'`, and `-c '\d schema.table'`.
  Match quoted identifier casing. Use separate `-c` arguments for SQL and meta-commands.
- Use `--csv` for structured rows or `-At` for scalars. Unaligned output defaults
  to `|` separators and does not escape delimiters within values.
- Use `-f FILE` for scripts. Bind values with `-v name="$VALUE"` and `:'name'` in
  the script; use `:"name"` for identifiers. Variable substitution does not work in `-c` SQL.
- For atomic scripts, add `-1` when all statements permit transactions and the
  script has no transaction-control commands. Check persisted results after writes.
- Unfamiliar syntax: `psql --help`, `psql --help=commands`, or `psql --help=variables`;
  use `-c '\h COMMAND'` for SQL help.
