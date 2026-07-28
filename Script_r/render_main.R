#!/usr/bin/env Rscript

# Render main figures --------
# Loads the shared helpers, audits panel values, and renders Figures 1-5.
# runtime options --------
options(stringsAsFactors = FALSE, warn = 1)
Sys.umask("0077")

# render Figure 1-5 --------
render_main_figures <- function(
    root,
    result_dir = Sys.getenv("HFMD_RESULT_DIR", unset = ""),
    output_dir = Sys.getenv("HFMD_MAIN_FIGURE_DIR", unset = "")) {
  root <- normalizePath(root, mustWork = TRUE)
  if (!nzchar(result_dir) || !nzchar(output_dir)) {
    stop("Run-scoped result and main-figure directories are required")
  }
  result_dir <- normalizePath(result_dir, mustWork = TRUE)

  # load helpers and configure render paths --------
  .libPaths(c(file.path(root, ".r_library"), .libPaths()))
  source(file.path(root, "Script_r", "common.R"), local = FALSE)
  source(file.path(root, "Script_r", "value_audit.R"), local = FALSE)
  run_id <- require_hfmd_run_id(always = TRUE)
  result_dir <- assert_hfmd_run_scoped_path(result_dir, run_id)
  output_dir <- assert_hfmd_run_scoped_output_path(output_dir, run_id)
  visual_contract_path <- visual_contract_for_render(root)
  old_render_paths <- options(
    hfmd.project_root = root,
    hfmd.result_dir = result_dir,
    hfmd.output_dir = output_dir,
    hfmd.visual_contract = visual_contract_path,
    hfmd.render_success_path = file.path(output_dir, "render_success.json"),
    hfmd.output_name_override = c(
      figure2_community_balance = "figure3_community_balance",
      figure3_age_ecology = "figure4_age_ecology",
      figure4_evidence_boundaries = "figure5_evidence_boundaries"
    )
  )
  on.exit(options(old_render_paths), add = TRUE)
  # clear stale outputs --------
  main_scripts <- c(
    "figure1_ecological_atlas.R",
    "figure2_county_ecological_effects.R",
    "figure2_community_balance.R",
    "figure3_age_ecology.R",
    "figure4_evidence_boundaries.R"
  )
  dir.create(output_dir, recursive = TRUE, showWarnings = FALSE, mode = "0700")
  unlink(list.files(
    output_dir,
    pattern = "^figure[1-5].*[.](pdf|svg|tiff|png)$",
    full.names = TRUE
  ))
  # A partial render invalidates the full-workflow success record. render_all.R
  # recreates it only after both groups finish successfully.
  unlink(file.path(output_dir, "render_success.json"))

  # audit values and render panels --------
  panel_audit <- write_panel_value_audit(result_dir, output_dir, root)
  for (figure_script in main_scripts) {
    source(
      file.path(root, "Script_r", "figures", figure_script),
      local = new.env(parent = globalenv())
    )
  }
  manifest <- write_figure_manifest(
    output_dir,
    figure_ids = paste0("figure", 1:5),
    require_complete = TRUE
  )

  invisible(list(panel_audit = panel_audit, manifest = manifest, output_dir = output_dir))
}

# command-line entry point --------
if (sys.nframe() == 0L) {
  all_args <- commandArgs(trailingOnly = FALSE)
  script_arg <- grep("^--file=", all_args, value = TRUE)
  if (!length(script_arg)) stop("Unable to locate render_main.R")
  script_path <- normalizePath(sub("^--file=", "", script_arg[[1]]), mustWork = TRUE)
  project_root <- normalizePath(file.path(dirname(script_path), ".."), mustWork = TRUE)

  args <- commandArgs(trailingOnly = TRUE)
  input_dir <- if (length(args) >= 1) args[[1]] else Sys.getenv("HFMD_RESULT_DIR", unset = "")
  figure_dir <- if (length(args) >= 2) args[[2]] else Sys.getenv("HFMD_MAIN_FIGURE_DIR", unset = "")
  render_main_figures(project_root, input_dir, figure_dir)
  message("Rendered Figure 1-5: ", normalizePath(figure_dir, mustWork = FALSE))
}
