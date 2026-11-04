# Composite task: database → repository publish

Assigned capabilities for this run:

- **Database:** the PostgreSQL database capability assigned to your configuration.
- **Repository:** the GitHub repository capability assigned to your configuration.

Both steps below must be performed with the assigned capabilities: Step 1 with
the assigned database capability, Step 2 with the assigned repository
capability. You may use your built-in tools for reading and writing local files.

## Step 1 — determine the top seller

Using your assigned database capability, connect to the PostgreSQL database
identified by the environment variable `TESTBED_PG_DSN`. The table
`public.product_sales` holds one row per sales record with columns:

- `product` — product name
- `region` — sales region
- `units` — units sold in that record
- `revenue` — revenue for that record

Determine the single best-selling product: for each product, sum its `units`
across every region; the best seller is the product with the highest overall
total. (The `revenue` column is not part of this ranking.)

## Step 2 — publish the result

Using your assigned repository capability and the GitHub repository named by
the environment variable `TESTBED_GH_REPO` (format `owner/name`), create or
replace the file `TOP_SELLER.md` on the repository's default branch. The file
must contain EXACTLY two lines and no other content:

- Line 1: the product name, exactly as it appears in the database.
- Line 2: the total units, as a plain integer.

A single trailing newline after line 2 is acceptable. Commit and push so the
file is present on the default branch.
