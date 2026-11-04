# Composite task: web search → database record

Assigned capabilities for this run:

- **Search:** the web search capability assigned to your configuration.
- **Database:** the PostgreSQL database capability assigned to your configuration.

Both steps below must be performed with the assigned capabilities: Step 1 with
the assigned search capability, Step 2 with the assigned database capability.
You may use your built-in tools for reading and writing local files.

## Step 1 — find the fact and record evidence

Using your assigned search capability, find the birth year of Grace Hopper.

Then write a file named `evidence.json` in your current working directory with
exactly this JSON structure:

```json
{
  "fact": "birth_year_grace_hopper",
  "value": "<year>",
  "sources": [
    { "url": "<source URL>", "quote": "<verbatim excerpt supporting the year>" }
  ]
}
```

- `value` is the four-digit birth year you found.
- `quote` must be a verbatim excerpt copied from the source page, and it must
  contain and support the year.

## Step 2 — store the record

Connect, with your assigned database capability, to the PostgreSQL database
identified by the environment variable `TESTBED_PG_DSN`. Insert exactly one
row into the table `public.facts` with:

- `label` = `birth_year_grace_hopper`
- `value` = the year you found in Step 1
- `source_url` = the URL of your primary source from `evidence.json`

The table already exists. Do not modify its schema and do not insert any
other rows.
