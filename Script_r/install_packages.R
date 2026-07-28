#!/usr/bin/env Rscript

# Restore locked R packages --------
# Recreates the project library and verifies the package and R versions.
# resolve project paths --------
args <- commandArgs(trailingOnly = TRUE)
root <- if (length(args) >= 1L) normalizePath(args[[1L]], mustWork = TRUE) else normalizePath(".", mustWork = TRUE)
library_dir <- file.path(root, ".r_library")
dir.create(library_dir, recursive = TRUE, showWarnings = FALSE, mode = "0700")
.libPaths(c(library_dir, .libPaths()))

# restore renv environment --------
lockfile <- file.path(root, "Script_r", "renv.lock")
if (!file.exists(lockfile)) stop("R lockfile is missing: ", lockfile)
if (!requireNamespace("renv", quietly = TRUE)) {
  install.packages("renv", repos = "https://cloud.r-project.org")
}
renv::restore(project = root, lockfile = lockfile, library = library_dir, prompt = FALSE, clean = FALSE)

# verify restored versions --------
lock <- jsonlite::fromJSON(lockfile, simplifyVector = FALSE)
expected <- vapply(lock$Packages, function(package) package$Version, character(1))
expected <- vapply(expected, function(version) as.character(package_version(version)), character(1))
observed <- vapply(names(expected), function(package) as.character(utils::packageVersion(package)), character(1))
if (!identical(unname(observed), unname(expected))) stop("Restored R package versions do not match renv.lock")
if (as.character(getRversion()) != lock$R$Version) stop("R version does not match renv.lock: expected ", lock$R$Version)
print(observed)
