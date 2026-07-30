# Hunan HFMD study: data, code and reproducible results

This repository accompanies the study:

> *Pathogen redistribution and syndrome-level HFMD burden after EV-A71 vaccine
> introduction in Hunan, China*

It contains the public data, analysis script and generated results needed to
inspect the released findings without exposing restricted surveillance
records.

## Repository contents

```text
data/
├── hunan_aggregate/   Disclosure-approved aggregate study tables
└── synthetic/         Fully synthetic input data for end-to-end validation

scripts/
└── reproduce.py       Rebuilds and checks all public results

results/
├── hunan_aggregate/   Key findings and figures from the public study tables
└── synthetic/         Results generated from the synthetic inputs
```

## Reproduce the results

Python 3.10 or newer is required. No third-party packages are needed.

```bash
git clone https://github.com/xmusphlkg/HN_HFMD_public.git
cd HN_HFMD_public
python3 scripts/reproduce.py
```

To verify that a clean rerun exactly matches the committed results:

```bash
python3 scripts/reproduce.py --check
```

A successful check prints:

```text
OK: committed results match a clean reproduction.
```

Input and output SHA-256 digests are recorded in the data and result manifests.

## Data scope

The ten files in `data/hunan_aggregate/` are province-level or model-summary
tables approved for public release. They include the model-averaged net-benefit
summary, signed pathogen contributions, predictive weights, age and
compensation stress analyses, and a summary-only recorded-severe comparison.
They support verification and re-plotting of the reported findings, but they do
not permit re-estimation of the restricted record-level analysis.

The files in `data/synthetic/` describe fictional regions and were generated
deterministically. They are not masked, perturbed or resampled Hunan records.
Their purpose is to demonstrate the complete public computation from input data
to results.

Individual records, exact dates, small-area identifiers, vaccination records,
fitted unit-level panels, draw-level outputs, bootstrap replicates, candidate
member files and internal analysis receipts are not distributed.

## Licence and citation

The code is released under the BSD 3-Clause licence. The aggregate Hunan tables
are licensed under CC BY 4.0, and the synthetic data under CC0 1.0. Dataset-
specific notices are stored with the corresponding files in `data/`.

Citation information is provided in `CITATION.cff`.
