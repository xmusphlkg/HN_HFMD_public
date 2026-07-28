#!/usr/bin/env Rscript

# R-only vector graphical-abstract smoke test on a run-scoped synthetic gate summary.
options(stringsAsFactors = FALSE, warn = 1)
script_path <- normalizePath(sub("^--file=", "", grep("^--file=", commandArgs(FALSE), value = TRUE)[[1L]]), mustWork = TRUE)
root <- normalizePath(file.path(dirname(script_path), "..", ".."), mustWork = TRUE)
.libPaths(c(file.path(root, ".r_library"), .libPaths()))
options(hfmd.project_root = root)
source(file.path(root, "Script_r", "common.R"), local = FALSE)
source(file.path(root, "Script_r", "render_graphical_abstract.R"), local = FALSE)

run_id <- "20000101T000000Z-00000000-graphical"
temporary <- tempfile("hfmd-graphical-abstract-")
run_root <- file.path(temporary, run_id)
config_dir <- file.path(run_root, "config")
reporting_dir <- file.path(run_root, "reporting")
dir.create(config_dir, recursive = TRUE, mode = "0700")
dir.create(reporting_dir, recursive = TRUE, mode = "0700")

source_contract <- read_hfmd_visual_contract(file.path(root, "config", "visual_contract.yaml"))
snapshot <- list(
  resources = list(visual_contract = list(
    main_figures = unname(source_contract$figures[1:5]),
    supplementary_figures = unname(source_contract$figures[6:15])
  )),
  source_hashes = list(visual_contract.yaml = source_contract$resource_sha256)
)
snapshot_path <- file.path(config_dir, "config.snapshot.json")
jsonlite::write_json(snapshot, snapshot_path, auto_unbox = TRUE)

summary_path <- file.path(reporting_dir, "graphical_abstract_gated_summary.csv")
parent_hash <- paste(rep("b", 64), collapse = "")
summary <- data.table(
  run_id = run_id,
  parent_manifest_sha256 = parent_hash,
  profile = "synthetic",
  evidence_layer = c("target", "community", "age", "boundary"),
  label = c("Target burden", "Community balance", "Age distribution", "Evidence boundary"),
  estimate = c(-0.35, 0.08, 0.81, NA_real_),
  interval_low = c(-0.51, -0.02, 0.74, NA_real_),
  interval_high = c(-0.18, 0.18, 0.88, NA_real_),
  unit = c("relative", "relative", "share", ""),
  gate_status = c("pass", "conditional", "stable", "not_evaluated"),
  display_order = 1:4
)
data.table::fwrite(summary, summary_path)

Sys.setenv(
  HFMD_RUN_ID = run_id,
  HFMD_PROFILE = "synthetic",
  HFMD_VISUAL_CONTRACT = snapshot_path
)
output_dir <- file.path(reporting_dir, "graphical_abstract")
manifest <- render_graphical_abstract(root, run_root, summary_path, output_dir)
stopifnot(nrow(manifest) == 2L)
stopifnot(all(file.exists(file.path(output_dir, c("graphical_abstract.pdf", "graphical_abstract.svg")))))
stopifnot(file.exists(file.path(output_dir, "graphical_abstract_manifest.csv")))
stopifnot(all(manifest$run_id == run_id), all(manifest$synthetic_validation))
stopifnot(all(manifest$parent_manifest_sha256 == parent_hash))

unlink(temporary, recursive = TRUE, force = TRUE)
cat("graphical-abstract vector smoke checks passed\n")
