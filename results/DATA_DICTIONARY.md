# Data dictionary

## Assignment and provenance fields

`cell_id` identifies task × model × delivery mode × catalog × repetition.
`source_phase` identifies the physical execution version, even when later phases
link to its directory. Together they identify a distinct model attempt.
`is_selected_v7` marks the reported run of each cell, which is its last attempt;
`is_first_model_attempt` marks the earliest model execution for that assignment.
Neither flag removes historical spending. No zero-call setup incident appears
in the 509-model-attempt table.

`task`, `task_label`, `family`, `workload_group` and `capabilities` come from the
task catalog in `metadata/task_catalog.csv`. Capability lists use semicolons.
Controls have an empty required-capability list. Full catalogs still expose all
four capabilities; this column describes task requirements, not loaded tools.

`model` is `gpt6luna` or `glm53flash`; exact provider/API identifiers and `max`
thinking appear in `metadata/models.csv`. `catalog` is `full` or `required`;
`mode` is `eager`, `deferred` or `cli`; `rep` is 1, 2 or 3. Repetitions are
independent assignments, not automatic retries.

`max_total_tokens` and `deadline_s` preserve recorded per-attempt limits.
Different execution versions used different ceilings and instructions. Selection
and first-model sensitivity views do not erase those differences.

## Recorded metrics, not billing estimates

| Field | Meaning and restriction |
|---|---|
| `recorded_tokens` | Complete recorded session-usage total from the campaign summary; not a monetary cost. |
| `recorded_input_tokens_including_cache` | Harness-normalized input, including cache reads/writes. Do not add cache reads again. |
| `recorded_output_tokens` | Harness-normalized output; do not add reasoning tokens separately without checking provider mapping. |
| `recorded_cache_read_tokens` | Reported normalized cache-read tokens. Provider billing interpretation still needs verification. |
| `assistant_message_count` | Summary's `turns`: assistant message-end events. Not necessarily all billable model requests. |
| `model_tool_call_count` | Tool-call blocks in assistant messages. A bash call can contain multiple CLI operations. |
| `observed_request_payload_count` | Captured raw-request files counted by the observer. Not guaranteed to cover all auxiliary billing. |
| `first_assistant_input_tokens` | Input usage on the first assistant message with usage; includes prompt/history/serialization. **Not resident definitions.** |
| `reference_cost_usd` | Blank in this table; dated reference costs for the reported runs are in `analysis/run_components.csv` as `cost_usd`. |

`ledger_has_no_missing_usage` records the harness ledger check. It does not prove
that every provider-billed event is captured. Cache-write tokens, auxiliary
breakdowns, request-component attribution, residuals and billed costs are not
reconstructed from incomplete aggregate fields.

## Outcomes

`outcome` preserves the exported classification: `success`, `task_failure`,
`provider_error`, `budget_exceeded` or `audit_review`. `clean_success` is true
only for `success`; verifier pass alone is insufficient. `verifier_pass` and
`verifier_reward_present` distinguish grading evidence from missing grades.
`route_status` and `exposure_status` remain separate; route audits are conservative
heuristics. `process_status` is the recorded agent process status, not a new
adjudication. Original provider errors and route reviews are not reclassified.

## Summary columns

Every group keeps `model`, `catalog` and `mode` separate. Task-level groups have
three repetitions. `analysis_view` chooses the reported runs (`selected_v7`) or each cell's first model attempt.

- `attempts`, `tasks`, `clean_successes`, `clean_success_fraction`: denominator is
  all attempts in that view/group, including unsuccessful attempts.
- `verifier_passes`, `known_verifier_rewards`: counts of true flags; missing grades
  are not silently turned into verified task failures.
- `outcome_*`: counts for each preserved outcome.
- `total_recorded_tokens`: sum over all group attempts.
- `mean_recorded_tokens`: arithmetic mean; `median_recorded_tokens`: median;
  `sample_sd_recorded_tokens`: sample SD with denominator n−1; `min_*`, `max_*`:
  observed range. SD is blank for n=1. Task SDs describe three-repetition
  variation; pooled group SDs mix between-task and within-task variation. Neither
  is a standard error or confidence interval.
- `pooled_tokens_per_clean_success`: **sum of all attempt tokens / number of clean
  successes**, not average spending among successful runs and not mean task ratios.
  Blank when there are no clean successes.
- `task_groups_with_three_clean_successes` and
  `task_groups_with_three_attempts`: numerator and eligible denominator for an
  all-three-success task fraction. These selected/sensitivity counts are not an
  unqualified primary pass³ claim.
- `n_<metric>`, `mean_<metric>`: nonmissing observation count and arithmetic mean
  for each recorded metric. Missing values are excluded from that metric's mean,
  never replaced with zero; coverage must be checked before comparisons.
- `reported_cache_read_share_of_input`: pooled reported cache reads / pooled
  recorded input. Blank if any required observation is missing or input is zero.
  It is not a verified billing discount or causal estimate of cache reuse.
- `reference_cost_usd`, `reference_cost_per_clean_success_usd`: blank pending
  reference pricing. No claim of actual subscription expenditure is made.

`workload_subset` is `control`, `single_capability`, `composite`,
`tool_dependent` (single-capability + composite), or `all_tasks_descriptive`.
These overlap intentionally: never sum the five subsets together. Family groups
are descriptive. Tool-dependent pooled summaries exclude both controls.

CSV numbers retain calculation precision; presentation should round them. CSV
blanks mean unknown/unavailable/undefined. Provenance records source and output
SHA-256 hashes; regenerate all outputs after changing a source or build script.
