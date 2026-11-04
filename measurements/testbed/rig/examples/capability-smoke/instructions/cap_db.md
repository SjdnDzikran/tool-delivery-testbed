# Capability smoke: database

A disposable PostgreSQL database is available. Its connection URI is in the
environment variable `TESTBED_PG_DSN`.

1. Create (or drop and recreate) the table `smoke_items` with columns
   `id integer PRIMARY KEY` and `label text`.
2. Insert exactly two rows: `(1, 'alpha')` and `(2, 'beta')`.
3. Count the rows you inserted with a query.
4. Write that count as plain text (just the number) to `artifacts/db_rows.txt`.

Then stop.
