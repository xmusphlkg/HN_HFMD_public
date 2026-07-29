# Data

## `hunan_aggregate/`

Ten disclosure-approved aggregate tables support inspection of the study's
principal findings. They contain no individual records, exact dates,
county/city identifiers, small-area exposure series, draw-level outputs,
bootstrap replicates, candidate member files, internal receipts or fitted
unit-level panels.

These tables support result-level verification and public re-plotting, not
independent re-estimation of the restricted surveillance analysis. Field
definitions are in `hunan_aggregate/DATA_DICTIONARY.md`. The data are licensed
under CC BY 4.0.

## `synthetic/`

Four CSV files contain deterministic mathematical data for eight fictional
regions. They are not masked, perturbed, resampled or differentially private
versions of Hunan records. The data are licensed under CC0 1.0.

Each directory has a `manifest.json` containing SHA-256 digests checked before
the reproduction script performs any calculation.
