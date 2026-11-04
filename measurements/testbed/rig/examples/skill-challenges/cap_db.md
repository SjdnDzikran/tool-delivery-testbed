# Client-side CSV round trip

Use the disposable database in `TESTBED_PG_DSN`. Create `smoke_items` with columns
`id integer PRIMARY KEY` and `label text`. The supplied CSV has a header and five
records, including an embedded newline, a SQL NULL, and a distinct empty string:

```csv
id,label
1,"comma, inside"
2,"double ""quote"""
3,"line one
line two"
4,
5,""
```

Write these bytes to a local input file. Import them with psql's client-side
CSV-copy capability, not hand-written INSERT statements or server filesystem COPY.
Preserve the distinction between the fourth row's NULL and the fifth row's empty
string.

Export the entire table, ordered by id, through the client-side CSV-copy
capability to `artifacts/roundtrip.csv`, with its header and lossless CSV quoting.
Read back the persisted row count and write just that number followed by a newline
to `artifacts/db_rows.txt`. Then stop.
