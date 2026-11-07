---
name: brave-search
description: Use Brave Search CLI (`bx`) for web searches and current external information.
---

# Brave Search

`bx "query"` = `bx context "query"`; use it for grounded results. Run `bx help <mode>` for options.

- `context`: `--count N`; tune `--max-tokens` (2048–4096) and `--threshold strict|balanced|lenient`.
- `web`: raw results; `--count N`, `--result-filter`.
- `news`: `--count N`; `--freshness pd|pw|pm|py`.
- `answers`: cited synthesis; `--no-stream` for JSON.
- Other modes: `images`, `videos`, `places`, `suggest`, `spellcheck`.

Mode-specific flags: `--count`, `--include-site`, and `--exclude-site` work only with `context`, `web`, and `news`. Check `bx help <mode>` for unfamiliar options.

- Keep stderr visible; empty output may signal an error.
- Quote queries; a stray `"` can absorb flags into the query.
- jq paths vary: web `.web.results[]?` / `.discussions.results[]?`; news `.news.results[]?`; context `.grounding.generic[]?`.

For custom ranking on `context`/`web`/`news`, prefer `--goggles` over long `site:` chains: `$boost=N,site=DOMAIN`, `$downrank=N,site=DOMAIN`, `$discard,site=DOMAIN`, `/path/$boost=N`. A final `$discard` makes an allowlist. For 1–2 domains, use `--include-site`/`--exclude-site`.
