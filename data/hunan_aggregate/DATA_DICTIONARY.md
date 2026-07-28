# Public aggregate result data dictionary

## Common interpretation rules

- `reported-case proxy` denotes a surveillance-derived pathogen-specific
  quantity, not an observed infection count.
- `recorded-severe proxy` preserves the source surveillance classification and
  is not an individual severe-risk endpoint.
- `model-conditional` quantities compare paired model-defined vaccination and
  no-vaccination histories; they are not identified causal vaccine effects.
- Conditional bootstrap intervals and observation-anchored empirical ranges
  are separate uncertainty layers and must not be pooled.
- Empty interval fields indicate that the prespecified identification or
  denominator criterion was not met.

## File-level dictionary

| File | Rows represent | Important fields |
|---|---|---|
| `observation_adjustment_summary.csv` | Province-level observation diagnostics | `metric`, `value`, `unit`, `description` |
| `pathogen_composition_by_period.csv` | Prespecified epidemiological periods | period, years, annualized reported proxies and three pathogen shares |
| `model_conditional_balance.csv` | Primary all-age estimands | point estimate, conditional interval, observation-anchored range and interpretation |
| `model_conditional_balance_by_age.csv` | Evidence layer × age group | EV-A71 reduction, CV-A16 increase, net balance and retained fraction |
| `structural_sensitivity_summary.csv` | Prespecified scenario families | analysis count, pathogen-contrast ranges, net-positive count and exception |
| `annual_model_validation.csv` | Out-of-period test year | composite, total-case and pathogen-composition differences; positive differences favour M2 |
| `case_severity_burden_summary.csv` | Outcome family × comparison × estimand | point estimate, interval, replicate count, interval status and uncertainty interpretation |

## Missing values

Blank cells are encoded as empty CSV fields. `Not applicable` denotes a
structural or definitional non-applicability. Negative values are meaningful
signed contrasts unless the file-specific interpretation states otherwise.
