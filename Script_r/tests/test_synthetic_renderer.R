#!/usr/bin/env Rscript

# Full 5+10 R-only smoke render using tiny, fully synthetic contracts.
options(stringsAsFactors = FALSE, warn = 1)
script_path <- normalizePath(sub("^--file=", "", grep("^--file=", commandArgs(FALSE), value = TRUE)[[1L]]), mustWork = TRUE)
root <- normalizePath(file.path(dirname(script_path), "..", ".."), mustWork = TRUE)
.libPaths(c(file.path(root, ".r_library"), .libPaths()))
options(hfmd.project_root = root)
source(file.path(root, "Script_r", "common.R"), local = FALSE)
source(file.path(root, "Script_r", "render_synthetic_contract.R"), local = FALSE)

run_id <- "20000101T000000Z-00000000-visual-e2e"
temporary <- tempfile("hfmd-synthetic-render-")
run_root <- file.path(temporary, run_id)
eco_dir <- file.path(run_root, "analysis", "ecological")
dynamics_dir <- file.path(run_root, "analysis", "dynamics")
dir.create(eco_dir, recursive = TRUE, mode = "0700")
dir.create(dynamics_dir, recursive = TRUE, mode = "0700")
dir.create(file.path(run_root, "config"), recursive = TRUE, mode = "0700")

regions <- paste0("Synthetic Region ", LETTERS[1:4])
years <- 2019:2025
ecological <- data.table::CJ(synthetic_region = regions, year = years)
ecological[, `:=`(
  run_id = run_id,
  validation_scope = "synthetic_validation",
  weeks_observed = 52L,
  population = 50000 + 2500 * match(synthetic_region, regions),
  reported_cases = 80L + 4L * (year - min(years)) + 7L * match(synthetic_region, regions),
  typed_cases = 20L + 2L * (year - min(years)),
  typing_resolution_fraction = pmin(0.85, 0.45 + 0.04 * (year - min(years))),
  under_six_case_fraction = 0.74 + 0.01 * match(synthetic_region, regions),
  mean_vaccine_proxy = pmin(0.9, 0.08 + 0.11 * (year - min(years)))
)]
ecological[, cases_per_100000 := 1e5 * reported_cases / population]
data.table::fwrite(ecological, file.path(eco_dir, "annual_validation_metrics.csv"))

pathogens <- c("ev_a71", "cv_a16", "other_enterovirus")
pathogen <- data.table::CJ(year = years, pathogen_group = pathogens)
pathogen[, run_id := run_id]
pathogen[, validation_scope := "synthetic_validation"]
pathogen[, reported_cases := 120L + 10L * match(pathogen_group, pathogens) + 3L * (year - min(years))]
pathogen[, typed_cases := 24L + 4L * match(pathogen_group, pathogens)]
pathogen[, reported_case_fraction := reported_cases / sum(reported_cases), by = year]
pathogen[, typed_case_fraction := typed_cases / sum(typed_cases), by = year]
pathogen[, mean_vaccine_proxy := pmin(0.9, 0.08 + 0.11 * (year - min(years)))]
data.table::fwrite(pathogen, file.path(dynamics_dir, "annual_pathogen_validation.csv"))

typing <- data.table::CJ(synthetic_region = regions, year = years)
typing[, `:=`(
  run_id = run_id,
  validation_scope = "synthetic_validation",
  resolved_pathogen_cases = 30L + year - min(years),
  not_tested_cases = 50L - 2L * (year - min(years)),
  typing_eligible_cases = 100L,
  resolved_pathogen_fraction = 0.30 + 0.025 * (year - min(years))
)]
data.table::fwrite(typing, file.path(dynamics_dir, "typing_selection_validation.csv"))

rolling <- data.table(
  run_id = run_id,
  validation_scope = "synthetic_validation",
  validation_model = "synthetic_naive_baseline",
  test_year = years,
  observed_total_cases = 900 + 25 * seq_along(years),
  predicted_total_cases = 885 + 23 * seq_along(years),
  total_case_log_score = -5.8 + 0.08 * seq_along(years),
  typing_log_score = -2.9 + 0.04 * seq_along(years),
  joint_log_score = -8.7 + 0.12 * seq_along(years)
)
data.table::fwrite(rolling, file.path(dynamics_dir, "rolling_origin_validation.csv"))

# Exercise immutable JSON-snapshot loading rather than current-source lookup.
source_contract <- read_hfmd_visual_contract(file.path(root, "config", "visual_contract.yaml"))
snapshot <- list(
  resources = list(visual_contract = list(
    main_figures = unname(source_contract$figures[1:5]),
    supplementary_figures = unname(source_contract$figures[6:15])
  )),
  source_hashes = list(visual_contract.yaml = source_contract$resource_sha256)
)
snapshot_path <- file.path(run_root, "config", "config.snapshot.json")
jsonlite::write_json(snapshot, snapshot_path, auto_unbox = TRUE)

Sys.setenv(
  HFMD_RUN_ID = run_id,
  HFMD_PROFILE = "ci",
  HFMD_VISUAL_CONTRACT = snapshot_path,
  HFMD_SYNTHETIC_PNG_DPI = "72",
  HFMD_SYNTHETIC_TIFF_DPI = "72"
)
main_dir <- file.path(run_root, "figures", "main")
supplementary_dir <- file.path(run_root, "figures", "supplementary")
render_synthetic_contract(root, run_root, main_dir, supplementary_dir)

main_files <- list.files(main_dir, pattern = "^figure[1-5].*[.](pdf|svg|png|tiff)$")
supplementary_files <- list.files(supplementary_dir, pattern = "^figureS([1-9]|10).*[.](pdf|svg|png|tiff)$")
stopifnot(length(main_files) == 20L, length(supplementary_files) == 40L)
stopifnot(file.exists(file.path(main_dir, "synthetic_render_success.json")))
main_manifest <- data.table::fread(file.path(main_dir, "figure_manifest.csv"))
supplementary_manifest <- data.table::fread(file.path(supplementary_dir, "figure_manifest.csv"))
stopifnot(nrow(main_manifest) == 20L, nrow(supplementary_manifest) == 40L)
stopifnot(all(main_manifest$run_id == run_id), all(supplementary_manifest$run_id == run_id))
stopifnot(all(main_manifest$visual_contract_source_sha256 == sha256_file(snapshot_path)))

unlink(temporary, recursive = TRUE, force = TRUE)
cat("synthetic 5+10 render smoke checks passed\n")
