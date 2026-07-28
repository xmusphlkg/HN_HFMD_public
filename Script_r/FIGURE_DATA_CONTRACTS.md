# R figure-data contracts

Formal R figures consume immutable, run-scoped tables. The result directory
must be beneath a path component exactly equal to `HFMD_RUN_ID`; legacy
`AnalysisOutput/` and `Outcome/` paths are rejected. Every table below is read
from `RESULT_DIR/figure_data/` and must contain one `run_id` plus one lowercase
64-character `parent_manifest_sha256`.

All schemas are long form. `display_order` is numeric and controls only visual
ordering. `status` uses one of `pass`, `supports`, `stable`, `attenuated`,
`warning`, `reversed`, `fail`, `boundary`, or `not_estimated`. Point estimates
and intervals remain on their registered native scale; the R layer never
transforms heterogeneous estimands into a pooled effect.

## Figure 2

File: `figure2_county_ecological_effects.csv`

```text
run_id,parent_manifest_sha256,panel,model_id,model_group,outcome,estimand,
specification,effect_scale,estimate,interval_low,interval_high,null_value,
status,display_order
```

Panels `a`–`e` are required exactly once as non-empty groups. Panels `a`, `b`
and `d` are native-scale interval displays. Panels `c` and `e` are registered
status/specification matrices. `null_value` must be explicit because rate,
odds, hazard and additive scales do not share a common null.

## Figure S8

File: `figureS8_ecological_diagnostics.csv`

```text
run_id,parent_manifest_sha256,panel,model_id,model_group,diagnostic,label,
x,y,estimate,threshold,status,display_order
```

Panels `a`–`d` are required. They carry residual-versus-fitted values,
dispersion summaries, influence diagnostics, and the 55-model registry status
matrix, respectively.

## Figure S9

File: `figureS9_pathogen_pair_structures.csv`

```text
run_id,parent_manifest_sha256,panel,model_id,pathogen_pair,direction,fold,
component,metric,estimate,interval_low,interval_high,null_value,
boundary_distance,status,display_order
```

Panels `a`–`d` are required. Rolling score `component` values are `joint`,
`total_cases`, and `typing`. Boundary distance is non-negative, with zero
denoting the registered boundary.

## Figure S10

File: `figureS10_mechanism_recovery.csv`

```text
run_id,parent_manifest_sha256,panel,scenario,mechanism,metric,estimate,
interval_low,interval_high,target,status,display_order
```

Panels `a`–`d` are required and represent null false selection, positive-
mechanism bias, interval coverage, and the cross-scenario operating-
characteristic matrix.

## Synthetic 5 + 10 renderer

`render_synthetic_contract.R` intentionally uses the lightweight analysis
tables already emitted by the CI ecological and dynamics workers:

```text
analysis/ecological/annual_validation_metrics.csv
analysis/dynamics/annual_pathogen_validation.csv
analysis/dynamics/typing_selection_validation.csv
analysis/dynamics/rolling_origin_validation.csv
```

The canonical synthetic pathogen IDs are lowercase: `ev_a71`, `cv_a16`, and
`other_enterovirus`. They map to orange, teal and navy. The renderer does not
fabricate formal effects, counterfactuals, bootstrap distributions, pathogen-
pair fits, or recovery simulations; unavailable analyses are labelled as not
executed. Every page is marked `SYNTHETIC VALIDATION — NOT FOR SCIENTIFIC
INFERENCE`.

Set `HFMD_VISUAL_CONTRACT` to the run's immutable
`config/config.snapshot.json`. The R parser reads
`resources.visual_contract` directly and records both the snapshot-file hash
and the embedded visual-contract resource hash.

## Graphical abstract

`render_graphical_abstract.R` reads a gated summary CSV with:

```text
run_id,parent_manifest_sha256,profile,evidence_layer,label,estimate,
interval_low,interval_high,unit,gate_status,display_order
```

It accepts three to six ordered evidence layers. `gate_status` is one of
`pass`, `stable`, `conditional`, `downgraded`, `fail`, or `not_evaluated`.
Outputs are editable `graphical_abstract.svg` and `graphical_abstract.pdf`.
Synthetic/CI profiles receive the prominent validation label. No generative
image service is used.
