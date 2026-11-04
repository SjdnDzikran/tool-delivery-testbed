# Search request controls

Use the supplied Brave CLI to search the web for exactly:

    Universitas Gadjah Mada official website

The search request must use Indonesia (`id`) as its country, strict safe search,
disabled spellchecking, disabled extra snippets, and a server-side result count
of one. Do not fetch the result page.

Copy the returned top result's URL and title verbatim into `artifacts/brave.json`
as an object with exactly the keys `url` and `title`. Do not manufacture metadata
or locally truncate a larger response instead of requesting one result. Then stop.
