# Disclosure-selected aggregate result data

This directory contains a deliberately small, allowlisted release of aggregate
results supporting the principal claims of the Hunan HFMD study. The files are
copied or deterministically reduced from result-facing tables in the private
analysis repository. They are scientific result summaries, not synthetic data.

## Included files

- `observation_adjustment_summary.csv`: province-level label-resolution and
  observation-support diagnostics. Per-year and age/severity cell counts are
  intentionally omitted.
- `pathogen_composition_by_period.csv`: annualized reported HFMD proxies and
  observation-adjusted pathogen shares for five prespecified periods.
- `model_conditional_balance.csv`: primary paired-history EV-A71, CV-A16 and
  net reported-case-proxy contrasts.
- `model_conditional_balance_by_age.csv`: age-specific paired-history
  contrasts under the conditional and observation-anchored analyses.
- `structural_sensitivity_summary.csv`: result ranges across structural and
  exposure specifications, including the exposure-below-age-three boundary.
- `annual_model_validation.csv`: seven annual observation-updated
  out-of-period comparisons.
- `case_severity_burden_summary.csv`: aggregate reported-case and
  recorded-severe surveillance-period contrasts.

`SOURCE_ALLOWLIST.json` records the only private-repository sources permitted
in this release. `PUBLIC_DATA_MANIFEST.json` binds every released CSV to its
source and SHA-256 digest. See `DATA_DICTIONARY.md` for interpretation.

## Explicit exclusions

This release contains no manuscript files, individual or event-level records,
county/city identifiers, exact dates, weekly surveillance series, vaccination
records, small-area population denominators, bootstrap replicates, fitted
unit-level panels, internal candidate outputs or disclosure-review material.
It also excludes result tables not needed to inspect the main claims.

The aggregate tables do not permit end-to-end reconstruction of the restricted
surveillance analysis. The public synthetic workflow remains the route for
testing code and data contracts without exposing governed inputs.

## Licence and citation

These disclosure-selected aggregate result tables are provided under
CC BY 4.0; see `../RESULT_DATA_LICENSE`. Cite the associated article and the
versioned public repository release when reusing them.
