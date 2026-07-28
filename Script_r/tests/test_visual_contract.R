#!/usr/bin/env Rscript

# Minimal dependency-free smoke checks for the executable visual contract.
options(stringsAsFactors = FALSE, warn = 2)
root <- normalizePath(file.path(dirname(sub("^--file=", "", grep("^--file=", commandArgs(FALSE), value = TRUE)[[1L]])), "..", ".."), mustWork = TRUE)
.libPaths(c(file.path(root, ".r_library"), .libPaths()))
options(hfmd.project_root = root, hfmd.visual_contract = file.path(root, "config", "visual_contract.yaml"))
source(file.path(root, "Script_r", "common.R"), local = FALSE)

contract <- read_hfmd_visual_contract()
stopifnot(length(contract$figures) == 15L)
stopifnot(identical(names(contract$figures)[1:5], paste0("figure", 1:5)))
stopifnot(identical(names(contract$figures)[6:15], paste0("figureS", 1:10)))
stopifnot(all(vapply(contract$figures, function(x) identical(x$export_formats, c("pdf", "svg", "png", "tiff")), logical(1))))
stopifnot(contract$figures$figure1$height_in == 8.0)
stopifnot(contract$figures$figure3$height_in == 6.6)
stopifnot(contract$figures$figure4$height_in == 7.6)
stopifnot(contract$figures$figure5$height_in == 7.8)

r_files <- c(
  file.path(root, "Script_r", "common.R"),
  file.path(root, "Script_r", "render_main.R"),
  file.path(root, "Script_r", "render_appendix.R"),
  file.path(root, "Script_r", "render_all.R"),
  file.path(root, "Script_r", "render_synthetic_contract.R"),
  file.path(root, "Script_r", "render_graphical_abstract.R"),
  list.files(file.path(root, "Script_r", "figures"), pattern = "[.]R$", full.names = TRUE)
)
invisible(lapply(r_files, parse))

run_id <- "20000101T000000Z-00000000-smoke"
Sys.setenv(HFMD_RUN_ID = run_id, HFMD_PROFILE = "synthetic")

temporary <- tempfile("hfmd-r-visual-smoke-")
dir.create(temporary, recursive = TRUE, mode = "0700")
run_result <- file.path(temporary, run_id, "analysis")
dir.create(file.path(run_result, "figure_data"), recursive = TRUE, mode = "0700")
contract_path <- file.path(run_result, "figure_data", "smoke.csv")
data.table::fwrite(
  data.table(
    run_id = run_id,
    parent_manifest_sha256 = paste(rep("a", 64), collapse = ""),
    panel = "a",
    value = 1
  ),
  contract_path
)
smoke_data <- read_run_scoped_figure_contract(run_result, "smoke.csv", c("panel", "value"))
stopifnot(nrow(smoke_data) == 1L, smoke_data$value[[1L]] == 1)

figure_dir <- file.path(temporary, "figures")
options(hfmd.png_dpi = 72L, hfmd.tiff_dpi = 72L)
smoke_plot <- ggplot(data.table(x = 1:3, y = c(1, 3, 2)), aes(x, y)) +
  geom_line(colour = hfmd_palette[["teal"]]) +
  geom_point(colour = hfmd_palette[["orange"]])
paths <- save_figure_bundle(smoke_plot, figure_dir, "figure2_county_ecological_effects")
stopifnot(identical(names(paths), c("pdf", "svg", "png", "tiff")))
stopifnot(all(file.exists(paths)), all(file.info(paths)$size > 0))

options(hfmd.output_name_override = c(figure2_community_balance = "figure3_community_balance"))
stopifnot(identical(resolve_figure_output_name("figure2_community_balance"), "figure3_community_balance"))
stopifnot(identical(figure_contract_entry("figure2_community_balance")$figure_id, "figure3"))

Sys.setenv(HFMD_RUN_ID = "", HFMD_PROFILE = "restricted")
formal_failure <- tryCatch({ require_hfmd_run_id(); FALSE }, error = function(error) TRUE)
stopifnot(formal_failure)

unlink(temporary, recursive = TRUE, force = TRUE)
cat("visual-contract smoke checks passed\n")
