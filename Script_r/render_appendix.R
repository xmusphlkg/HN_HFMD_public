#!/usr/bin/env Rscript

# Render supplementary figures --------
# Loads the shared helpers and renders Figures S1-S10.
# runtime options --------
options(stringsAsFactors = FALSE, warn = 1)
Sys.umask("0077")

# render Figure S1-S10 --------
render_appendix_figures <- function(
    root,
    result_dir = Sys.getenv("HFMD_RESULT_DIR", unset = ""),
    output_dir = Sys.getenv("HFMD_SUPPLEMENTARY_FIGURE_DIR", unset = ""),
    main_output_dir = Sys.getenv("HFMD_MAIN_FIGURE_DIR", unset = "")) {
  root <- normalizePath(root, mustWork = TRUE)
  if (!nzchar(result_dir) || !nzchar(output_dir)) {
    stop("Run-scoped result and supplementary-figure directories are required")
  }
  result_dir <- normalizePath(result_dir, mustWork = TRUE)

  # load helpers and configure render paths --------
  .libPaths(c(file.path(root, ".r_library"), .libPaths()))
  source(file.path(root, "Script_r", "common.R"), local = FALSE)
  run_id <- require_hfmd_run_id(always = TRUE)
  result_dir <- assert_hfmd_run_scoped_path(result_dir, run_id)
  output_dir <- assert_hfmd_run_scoped_output_path(output_dir, run_id)
  if (nzchar(main_output_dir)) {
    main_output_dir <- assert_hfmd_run_scoped_output_path(main_output_dir, run_id)
  }
  visual_contract_path <- visual_contract_for_render(root)
  old_render_paths <- options(
    hfmd.project_root = root,
    hfmd.result_dir = result_dir,
    hfmd.output_dir = output_dir,
    hfmd.visual_contract = visual_contract_path,
    hfmd.render_success_path = if (nzchar(main_output_dir)) file.path(main_output_dir, "render_success.json") else ""
  )
  on.exit(options(old_render_paths), add = TRUE)
  # clear stale outputs --------
  appendix_scripts <- c(
    "figureS1_analytic_workflow.R",
    "figureS2_annual_model_fit.R",
    "figureS3_contact_matrix.R",
    "figureS4_vaccine_proxy.R",
    "figureS5_bootstrap_estimands.R",
    "figureS6_pathogen_phenology.R",
    "figureS7_typing_diagnostics.R",
    "figureS8_ecological_diagnostics.R",
    "figureS9_pathogen_pair_structures.R",
    "figureS10_mechanism_recovery.R"
  )
  dir.create(output_dir, recursive = TRUE, showWarnings = FALSE, mode = "0700")
  unlink(list.files(
    output_dir,
    pattern = "^figureS([1-9]|10).*[.](pdf|svg|tiff|png)$",
    full.names = TRUE
  ))
  # Running only the appendix is not a complete validated render.
  invalidate_figure_render_success()

  # render supplementary panels --------
  for (figure_script in appendix_scripts) {
    source(
      file.path(root, "Script_r", "figures", figure_script),
      local = new.env(parent = globalenv())
    )
  }
  manifest <- write_figure_manifest(
    output_dir,
    figure_ids = paste0("figureS", 1:10),
    require_complete = TRUE
  )

  invisible(list(manifest = manifest, output_dir = output_dir))
}

# command-line entry point --------
if (sys.nframe() == 0L) {
  all_args <- commandArgs(trailingOnly = FALSE)
  script_arg <- grep("^--file=", all_args, value = TRUE)
  if (!length(script_arg)) stop("Unable to locate render_appendix.R")
  script_path <- normalizePath(sub("^--file=", "", script_arg[[1]]), mustWork = TRUE)
  project_root <- normalizePath(file.path(dirname(script_path), ".."), mustWork = TRUE)

  args <- commandArgs(trailingOnly = TRUE)
  input_dir <- if (length(args) >= 1) args[[1]] else Sys.getenv("HFMD_RESULT_DIR", unset = "")
  figure_dir <- if (length(args) >= 2) args[[2]] else Sys.getenv("HFMD_SUPPLEMENTARY_FIGURE_DIR", unset = "")
  render_appendix_figures(project_root, input_dir, figure_dir)
  message("Rendered Figure S1-S10: ", normalizePath(figure_dir, mustWork = FALSE))
}
