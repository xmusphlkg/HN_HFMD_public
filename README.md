# Hunan HFMD study: aggregate data, code and reproducible summaries

This repository accompanies the study:

> *Pathogen redistribution and syndrome-level HFMD burden after EV-A71 vaccine
> introduction in Hunan, China*

It provides disclosure-approved aggregate study tables, a synthetic validation
workflow and generated summaries without exposing restricted surveillance
records.

## Scientific scope

The manuscript treats the observation-standardized surveillance analyses as
the primary evidence. These analyses distinguish changes in pathogen
composition from changes in absolute reported burden and recorded-severe
burden.

The paired-history ensemble is a secondary post hoc exploratory analysis. It
compares model-defined vaccination and no-vaccination histories and reports an
all-pathogen reported-case balance conditional on the specified models and
exposure mapping. It is not an individual vaccine-effect estimate or an
identified causal count. The manuscript also reports a direction-reversing
sensitivity when ecological exposure is restricted to children younger than
3 years; that sensitivity is outside the primary-mapping ensemble interval.

Version 0.2.0 retains several legacy machine-readable filenames and field names
containing `net_benefit` for schema compatibility. In the manuscript and in
interpretation of this release, these fields denote the post hoc paired-history
all-pathogen reported-case balance. A legacy development decision label should
not be interpreted as a confirmatory scientific claim.

## Repository contents

```text
data/
├── hunan_aggregate/   Disclosure-approved aggregate study tables
└── synthetic/         Fully synthetic input data for end-to-end validation

scripts/
└── reproduce.py       Rebuilds the public result summaries

results/
├── hunan_aggregate/   Summaries generated from the aggregate study tables
└── synthetic/         Results generated from the synthetic inputs
```

## Reproduce the summaries

Python 3.10 or newer is required. No third-party packages are needed.

```bash
git clone https://github.com/xmusphlkg/HN_HFMD_public.git
cd HN_HFMD_public
python3 scripts/reproduce.py
```

The optional check command compares a clean rerun with the committed examples:

```bash
python3 scripts/reproduce.py --check
```

## Data scope

The ten files in `data/hunan_aggregate/` are province-level or model-summary
tables approved for public release. They include observation-support and
pathogen-composition summaries, the primary-mapping paired-history
reported-case balance, signed pathogen contributions, predictive weights, age
and compensation stress analyses, annual model evaluation, reported and
recorded-severe period contrasts, and a summary-only recorded-severe
comparison. They support result-level inspection and re-plotting but do not
permit re-estimation of the restricted record-level analyses.

The files in `data/synthetic/` describe fictional regions and were generated
deterministically. They are not masked, perturbed or resampled Hunan records.
Their purpose is to demonstrate the public computation from input data to
result summaries.

Individual records, exact dates, small-area identifiers, vaccination records,
fitted unit-level panels, draw-level outputs, bootstrap replicates and
candidate member files are not distributed.

## Licence and citation

The code is released under the BSD 3-Clause licence. The aggregate Hunan tables
are licensed under CC BY 4.0, and the synthetic data under CC0 1.0. Dataset-
specific notices are stored with the corresponding files in `data/`.

Citation information is provided in `CITATION.cff`.
