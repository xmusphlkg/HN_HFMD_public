# Multiscale HFMD research platform

This public repository contains analysis code, deterministic synthetic data,
workflow configuration, visual templates, documentation, and a
disclosure-selected set of aggregate Hunan result tables for studying the
ecological effects of EV-A71 vaccination. It contains no restricted Hunan
record-level or small-area observations.

Run the two-core public smoke workflow with:

```bash
uv sync --locked --extra analysis --extra workflow --extra dev
uv run --locked hfmd run --target all --profile ci
```

This executes the complete synthetic analysis DAG: data contracts, ecological
and dynamics validation modules, and all 5 main and 10 supplementary figures.
The workflow can exercise local reporting checks, but manuscript and submission
artifacts are deliberately excluded from this public release. Every retained
output is visibly marked `synthetic_validation`; none is a scientific estimate
for Hunan.

The synthetic fixture uses fictional regions and mathematical data-generating
functions. It is not a masked, perturbed, resampled, or differentially private
version of the restricted dataset. See `CONTROLLED_DATA_ACCESS.md` for the
process required to reproduce restricted analyses.

## Disclosure-selected aggregate results

The `public_data/` directory contains seven province-level or model-summary
tables selected to support inspection of the principal findings without
disclosing the restricted surveillance inputs. The data dictionary identifies
the unit and interpretation of every file, while `PUBLIC_DATA_MANIFEST.json`
binds each public file to its source revision and SHA-256 digest.

This release does not include the manuscript, individual or event records,
county/city identifiers, exact dates, weekly surveillance series, small-area
exposures, bootstrap replicates, fitted unit-level panels, or internal
candidate and audit files. It supports result-level inspection, not independent
reconstruction of the restricted analysis.

To refresh these files from an authorized private checkout:

```bash
python public_repo/sync_public_data.py --source-root ../hunanHFMD
```

## Licensing

Code is licensed under BSD-3-Clause, generated synthetic data under CC0-1.0,
the aggregate result tables in `public_data/` under CC-BY-4.0, and prose
documentation under CC-BY-4.0. See `NOTICE` for the boundary between these
materials.
