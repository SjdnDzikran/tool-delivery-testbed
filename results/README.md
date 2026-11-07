# Results

Numeric results from the main campaign, in which 12 tasks ran under eager MCP, deferred MCP, and CLI plus skills, on GPT-6 Luna and GLM 5.3 Flash, with two catalog settings and three repetitions. That gives 432 cells. Raw requests, prompts, model answers, session traces, and credentials are not included.

## Files

| Path | Contents |
|---|---|
| `data/selected_assignments.csv` | The 432 reported runs, including failures |
| `data/attempts.csv` | All 509 recorded model attempts, with flags for reported runs and first attempts |
| `summaries/` | Summaries by task, by model and configuration, and by family |
| `by_model/`, `by_catalog/` | Per-task summaries of the reported runs |
| `metadata/` | Task catalog and model identifiers |
| `analysis/run_components.csv` | Input components, usage, and reference cost per reported run |
| `analysis/run_activations.csv` | Tool and skill activations per reported run |
| `analysis/summary.json` | Pooled results, statistics, price sweep, and token-saving checks |
| `analysis/build_analysis.py` | Rebuilds `summary.json` from the two run tables and the attempt table |
| `figures/build_figures.py` | Draws the result figures |
| `DATA_DICTIONARY.md` | Field definitions, units, and limits |

Attribution in `run_components.csv` was computed from private request captures by `measurements/testbed/rig/verification/analyze_components.py`, so that step cannot be rerun from this repository. The later steps can.

The label `selected_v7` and the column `is_selected_v7` mark reported runs. `source_phase` records the collection round of each attempt.

## Reported runs and excluded attempts

A clean success is a run whose verifier, route audit, and exposure audit all passed. The 432 reported runs contain 421 clean successes, 10 task failures, and one route review, with 184,919,683 recorded tokens.

Each cell reports its last attempt. The other 77 attempts, which recorded 59,184,118 tokens, remain in `data/attempts.csv` and were excluded for these reasons:

1. **Corrected task instructions (72 attempts).** Two task instructions were incomplete or wrong, and all 72 cells of those tasks were rerun with corrected instructions and the same verifiers. The original attempts had produced 55 clean successes, 16 task failures, and one route review.
2. **Raised token limit (2 attempts).** One CLI cell stopped at limits of 3,000,000 and 4,000,000 recorded tokens. The limit was raised to 6,000,000 for all cells, and the next attempt passed with 2,369,763 tokens. This favours CLI plus skills.
3. **Provider errors (2 attempts).** A gateway time-out and a request rate limit ended these attempts before grading.
4. **Route review (1 attempt).** A rerun received the same outcome.

These decisions were made case by case after the outcomes were known. Task failures under the corrected instructions were not rerun.

## Costs

`cost_usd` is an API-equivalent estimate: recorded usage priced at the published standard rates accessed on 6 November 2026. It is not actual expenditure, since the runs used subscription access.

## Rebuild

With Python 3.11 or later, and SciPy for the analysis and Matplotlib for the figures, from the repository root:

```sh
python3 results/analysis/build_analysis.py
python3 results/figures/build_figures.py
```
