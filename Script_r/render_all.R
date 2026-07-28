#!/usr/bin/env Rscript

# Render all manuscript figures --------
# This entry point renders main and supplementary figures and records success.
# runtime options and project paths --------
options(stringsAsFactors = FALSE, warn = 1)
Sys.umask("0077")

all_args <- commandArgs(trailingOnly = FALSE)
script_arg <- grep("^--file=", all_args, value = TRUE)
if (!length(script_arg)) stop("Unable to locate render_all.R")
script_path <- normalizePath(sub("^--file=", "", script_arg[[1]]), mustWork = TRUE)
root <- normalizePath(file.path(dirname(script_path), ".."), mustWork = TRUE)

args <- commandArgs(trailingOnly = TRUE)
result_arg <- if (length(args) >= 1) args[[1]] else Sys.getenv("HFMD_RESULT_DIR", unset = "")
main_arg <- if (length(args) >= 2) args[[2]] else Sys.getenv("HFMD_MAIN_FIGURE_DIR", unset = "")
supplementary_arg <- if (length(args) >= 3) args[[3]] else Sys.getenv("HFMD_SUPPLEMENTARY_FIGURE_DIR", unset = "")
if (!nzchar(result_arg) || !nzchar(main_arg) || !nzchar(supplementary_arg)) {
  stop("Run-scoped RESULT_DIR, MAIN_DIR, and SUPPLEMENTARY_DIR are required")
}
result_dir <- normalizePath(result_arg, mustWork = TRUE)
main_dir <- normalizePath(main_arg, mustWork = FALSE)
supplementary_dir <- normalizePath(supplementary_arg, mustWork = FALSE)

# load render modules --------
.libPaths(c(file.path(root, ".r_library"), .libPaths()))
source(file.path(root, "Script_r", "render_main.R"), local = FALSE)
source(file.path(root, "Script_r", "render_appendix.R"), local = FALSE)
source(file.path(root, "Script_r", "common.R"), local = FALSE)
run_id <- require_hfmd_run_id(always = TRUE)

# render figure sets --------
main_render <- render_main_figures(root, result_dir, main_dir)
render_appendix_figures(root, result_dir, supplementary_dir, main_dir)
panel_audit <- main_render$panel_audit
render_visual_contract <- read_hfmd_visual_contract()

# write render record --------
font_match <- tryCatch(
  trimws(system2("fc-match", c("-f", shQuote("%{family}"), shQuote(hfmd_font_family)), stdout = TRUE)[[1]]),
  error = function(error) NA_character_
)
render_record <- list(
  status = "success",
  run_id = run_id,
  backend = "R",
  theme = "Script_r/common.R",
  requested_font = hfmd_font_family,
  matched_font = font_match,
  panel_value_audit = "panel_value_audit.csv",
  panel_value_checks = nrow(panel_audit),
  panel_value_checks_passed = sum(panel_audit$status == "PASS"),
  visual_contract_source = basename(render_visual_contract$path),
  visual_contract_source_sha256 = render_visual_contract$source_sha256,
  visual_contract_resource_sha256 = render_visual_contract$resource_sha256,
  main_figure_files = sort(basename(list.files(main_dir, pattern = "^figure[1-5].*[.](pdf|svg|png|tiff)$"))),
  supplementary_figure_files = sort(basename(list.files(supplementary_dir, pattern = "^figureS([1-9]|10).*[.](pdf|svg|png|tiff)$")))
)
record_path <- file.path(main_dir, "render_success.json")
jsonlite::write_json(render_record, record_path, auto_unbox = TRUE, pretty = TRUE)
Sys.chmod(record_path, mode = "0600")

message("Rendered Figure 1-5 and Figure S1-S10 with the canonical R workflow")
