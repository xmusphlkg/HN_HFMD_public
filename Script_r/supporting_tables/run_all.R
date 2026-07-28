#!/usr/bin/env Rscript

# Render supporting tables --------
# Formats standardized analysis outputs without fitting models or rendering figures.
# parse arguments and configure runtime --------
options(stringsAsFactors = FALSE, warn = 1)
Sys.umask("0077")
args <- commandArgs(trailingOnly = TRUE)
if (length(args) < 1L) stop("Usage: Rscript Script_r/supporting_tables/run_all.R PROJECT_ROOT [CONFIG_JSON]")

root <- normalizePath(args[[1L]], mustWork = TRUE)
config_path <- if (length(args) >= 2L) {
  normalizePath(args[[2L]], mustWork = TRUE)
} else {
  file.path(root, "Script_py", "config", "analysis.json")
}
library_dir <- file.path(root, ".r_library")
.libPaths(c(library_dir, .libPaths()))

# verify locked R environment --------
lockfile <- file.path(root, "Script_r", "renv.lock")
if (!file.exists(lockfile) || !requireNamespace("jsonlite", quietly = TRUE)) {
  stop("Locked R environment is unavailable; run Script_r/install_packages.R first")
}
lock <- jsonlite::fromJSON(lockfile, simplifyVector = FALSE)
expected_versions <- vapply(lock$Packages, function(package) package$Version, character(1))
expected_versions <- vapply(expected_versions, function(version) as.character(package_version(version)), character(1))
observed_versions <- vapply(names(expected_versions), function(package) {
  if (!requireNamespace(package, quietly = TRUE)) return(NA_character_)
  as.character(utils::packageVersion(package))
}, character(1))
if (!identical(unname(observed_versions), unname(expected_versions))) {
  mismatch <- names(expected_versions)[is.na(observed_versions) | observed_versions != expected_versions]
  stop("R package lock mismatch: ", paste(mismatch, collapse = ", "), ". Run Script_r/install_packages.R")
}
if (as.character(getRversion()) != lock$R$Version) {
  stop("R version does not match renv.lock: expected ", lock$R$Version)
}

# load table helpers and output paths --------
source(file.path(root, "Script_r", "supporting_tables", "common.R"), local = FALSE)
source(file.path(root, "Script_r", "supporting_tables", "tables.R"), local = FALSE)

config <- jsonlite::fromJSON(config_path, simplifyVector = TRUE)
output <- file.path(root, config$output_dir)
paths <- list(
  output = output,
  tables = file.path(output, "tables"),
  publication_tables = file.path(root, "Outcome", "tables", "supporting_ecological"),
  diagnostics = file.path(output, "diagnostics")
)
for (path in unname(paths[c("publication_tables", "diagnostics")])) {
  dir.create(path, recursive = TRUE, showWarnings = FALSE, mode = "0700")
}

# build publication tables --------
success_path <- file.path(paths$diagnostics, "r_table_success.json")
unlink(c(success_path, file.path(paths$diagnostics, "r_render_success.json")), force = TRUE)

message("Formatting supporting ecological-analysis tables")
make_publication_tables(paths)

# write session and completion record --------
session_path <- file.path(paths$diagnostics, "r_session_info.txt")
capture.output(sessionInfo(), file = session_path)
Sys.chmod(session_path, mode = "0600")

success <- list(
  status = "success",
  publication_tables = sort(basename(list.files(paths$publication_tables))),
  config = config_path,
  note = "R formatted standardized Python outputs into supporting tables and did not render manuscript figures or refit models.",
  r_code_md5 = as.list(tools::md5sum(list.files(
    file.path(root, "Script_r", "supporting_tables"), pattern = "[.]R$", full.names = TRUE
  ))),
  renv_lock_md5 = unname(tools::md5sum(lockfile))
)
jsonlite::write_json(success, success_path, auto_unbox = TRUE, pretty = TRUE)
Sys.chmod(success_path, mode = "0600")
message("Supporting table pipeline completed")
