# R visualization workflow

All manuscript visualization is implemented in R. The design is intentionally
split into a global visual layer and one script per figure.

## Global visual layer

Edit `common.R` for changes that must apply everywhere:

- `hfmd_palette`, pathogen colours, age colours and continuous colour scales;
- `theme_hfmd()` and panel-tag styling;
- shared data checks and number formatting;
- `save_figure_bundle()` and the executable `config/visual_contract.yaml`
  export settings (PDF/SVG/PNG/TIFF for every registered figure).

Figure scripts must call these shared objects. They should not redefine fixed
hex colours, global themes or graphics-device/export code.

## Figure scripts

```text
figures/figure1_ecological_atlas.R
figures/figure2_county_ecological_effects.R
figures/figure2_community_balance.R
figures/figure3_age_ecology.R
figures/figure4_evidence_boundaries.R
figures/figureS1_analytic_workflow.R
figures/figureS2_annual_model_fit.R
figures/figureS3_contact_matrix.R
figures/figureS4_vaccine_proxy.R
figures/figureS5_bootstrap_estimands.R
figures/figureS6_pathogen_phenology.R
figures/figureS7_typing_diagnostics.R
figures/figureS8_ecological_diagnostics.R
figures/figureS9_pathogen_pair_structures.R
figures/figureS10_mechanism_recovery.R
```

Each file is a straight, top-to-bottom script containing that figure's setup,
data transformation, geoms, scales, labels, patchwork layout and save call.
There is no `make_figure*()` wrapper, so every section can be run line by line
in RStudio; sourcing the complete file renders its formal output bundle.

## Run

Open the project through `HFMD.Rproj`, then directly source the figure being
edited. No setup call and no preview mode are required:

```r
source("Script_r/figures/figure2_community_balance.R")
source("Script_r/figures/figureS3_contact_matrix.R")
```

Each source operation loads `common.R` and reads the canonical analysis results.
The formal renderer writes PDF, SVG, PNG and TIFF at the dimensions registered
in the visual contract. Palette, theme, font and export settings remain
centralized in `common.R`. Restricted rendering requires `HFMD_RUN_ID`; the new
county and diagnostic figures always require a run-scoped `figure_data/`
contract carrying both `run_id` and `parent_manifest_sha256`.
The exact long-form schemas are documented in `FIGURE_DATA_CONTRACTS.md`.

```bash
# rebuild Figure 1-5 and the main-figure value audit (all paths are run-scoped)
Rscript Script_r/render_main.R RESULT_DIR MAIN_DIR

# rebuild Figure S1-S10
HFMD_MAIN_FIGURE_DIR=MAIN_DIR Rscript Script_r/render_appendix.R RESULT_DIR SUPPLEMENTARY_DIR

# rebuild both groups and write the complete render-success record
Rscript Script_r/render_all.R RESULT_DIR MAIN_DIR SUPPLEMENTARY_DIR
```

All three commands accept explicit paths. `render_main.R` and
`render_appendix.R` take `RESULT_DIR OUTPUT_DIR`; `render_all.R` takes
`RESULT_DIR MAIN_DIR APPENDIX_DIR`.
Set `HFMD_RUN_ID` for every complete render and point
`HFMD_VISUAL_CONTRACT` at the immutable run `config.snapshot.json`; formal
rendering fails if that snapshot variable is absent.

## Synthetic CI renderer

`render_synthetic_contract.R` is a separate fail-closed entry point for CI. It
reads only these run-scoped lightweight contracts:

```text
RUN_ROOT/analysis/ecological/annual_validation_metrics.csv
RUN_ROOT/analysis/dynamics/annual_pathogen_validation.csv
RUN_ROOT/analysis/dynamics/typing_selection_validation.csv
RUN_ROOT/analysis/dynamics/rolling_origin_validation.csv
```

It creates all 5 main and 10 supplementary bundles inside `RUN_ROOT`, marks
every page `SYNTHETIC VALIDATION — NOT FOR SCIENTIFIC INFERENCE`, and refuses
legacy `AnalysisOutput/` or `Outcome/` paths.

```bash
HFMD_RUN_ID=<run_id> HFMD_PROFILE=ci Rscript \
  Script_r/render_synthetic_contract.R RUN_ROOT MAIN_DIR SUPPLEMENTARY_DIR
```

## Code-only graphical abstract

`render_graphical_abstract.R` reads one run-scoped gated summary CSV and emits
editable `graphical_abstract.svg` and `graphical_abstract.pdf`. Required columns
are `run_id`, `parent_manifest_sha256`, `profile`, `evidence_layer`, `label`,
`estimate`, `interval_low`, `interval_high`, `unit`, `gate_status`, and
`display_order`. Synthetic profiles receive the same prominent validation
label. The renderer uses only R vector code and does not call generative AI.

```bash
HFMD_RUN_ID=<run_id> HFMD_PROFILE=restricted Rscript \
  Script_r/render_graphical_abstract.R RUN_ROOT GATED_SUMMARY_CSV OUTPUT_DIR
```

Run the minimal visual-contract smoke test with:

```bash
Rscript Script_r/tests/test_visual_contract.R
```
