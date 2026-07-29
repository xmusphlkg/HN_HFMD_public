# Public aggregate result data dictionary

## Common interpretation rules

- `reported-case proxy` denotes a surveillance-derived pathogen-specific
  quantity, not an observed infection count.
- `recorded-severe proxy` preserves the source surveillance classification and
  is not an individual severe-risk endpoint.
- `model-ensemble` quantities compare paired model-defined vaccination and
  no-vaccination histories while propagating predictive-weight,
  pathway-structure, target-memory, vaccine-effectiveness and fitted-parameter
  uncertainty. They are not identified causal vaccine effects.
- Central model-ensemble intervals are quantiles over 2,000 formal draws. They
  are neither single-model confidence intervals nor posterior credible
  intervals.
- Predictive weights describe held-out predictive performance and are not
  mechanism probabilities.
- Recorded-severe reductions are independent descriptive surveillance-period
  contrasts and are not vaccination counterfactuals.
- Empty interval fields indicate that the prespecified identification or
  denominator criterion was not met.

## File-level dictionary

| File | Rows represent | Important fields |
|---|---|---|
| `observation_adjustment_summary.csv` | Province-level observation diagnostics | `metric`, `value`, `unit`, `description` |
| `pathogen_composition_by_period.csv` | Prespecified epidemiological periods | period, years, annualized reported proxies and three pathogen shares |
| `net_benefit_summary.csv` | All ages and five age scopes | point ensemble, draw count, net-benefit quantiles, retained fraction and frozen decision label |
| `pathogen_contribution_summary.csv` | Four signed all-age components | point ensemble, median, central 95% model-ensemble interval and sign interpretation |
| `predictive_weight_summary.csv` | Four structures and two pathway-inclusion summaries | point estimate and central 95% interval from 10,000 Bayesian-bootstrap weight resamples |
| `age_offset_sensitivity_summary.csv` | Five age groups × registered/doubled offsets | positive-draw probability and net-benefit quantiles |
| `net_benefit_q05_surface.csv` | 41 × 41 all-age compensation grid | CV-A16 and other-enterovirus multipliers, 5th-percentile net benefit and draw count |
| `recorded_severe_period_summary.csv` | Primary and two definition-aligned period comparisons | median reduction, central 95% surveillance-period interval and positive-replicate fraction |
| `annual_model_validation.csv` | Out-of-period test year | composite, total-case and pathogen-composition differences; positive differences favour M2 |
| `case_severity_burden_summary.csv` | Outcome family × comparison × estimand | point estimate, interval, replicate count, interval status and uncertainty interpretation |

## Missing values

Blank cells are encoded as empty CSV fields. `Not applicable` denotes a
structural or definitional non-applicability. Negative values are meaningful
signed contrasts unless the file-specific interpretation states otherwise. In
`pathogen_contribution_summary.csv`, negative non-target contributions offset
the EV-A71 reduction; positive net benefit favours the model-defined
vaccination history.
