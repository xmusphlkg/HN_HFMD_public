#!/usr/bin/env Rscript

# Code-only graphical abstract renderer.
# The renderer consumes a run-scoped, gate-evaluated summary contract and emits
# editable SVG/PDF vector outputs. It does not call any image-generation API.

options(stringsAsFactors = FALSE, warn = 1)
Sys.umask("0077")

graphical_abstract_contract_columns <- c(
  "run_id", "parent_manifest_sha256", "profile", "evidence_layer", "label",
  "estimate", "interval_low", "interval_high", "unit", "gate_status", "display_order"
)

path_inside_run_root <- function(path, run_root, must_work = TRUE) {
  resolved <- normalizePath(path, mustWork = must_work)
  root <- normalizePath(run_root, mustWork = TRUE)
  if (!startsWith(resolved, paste0(root, .Platform$file.sep))) {
    stop("Graphical-abstract path is outside the run staging root: ", resolved)
  }
  components <- strsplit(resolved, .Platform$file.sep, fixed = TRUE)[[1L]]
  if (any(components %in% c("AnalysisOutput", "Outcome"))) {
    stop("Graphical-abstract rendering refuses legacy AnalysisOutput/Outcome paths")
  }
  resolved
}

render_graphical_abstract <- function(root, run_root, summary_path, output_dir) {
  root <- normalizePath(root, mustWork = TRUE)
  .libPaths(c(file.path(root, ".r_library"), .libPaths()))
  source(file.path(root, "Script_r", "common.R"), local = FALSE)
  run_id <- require_hfmd_run_id(always = TRUE)
  run_root <- normalizePath(run_root, mustWork = TRUE)
  if (!run_id %in% strsplit(run_root, .Platform$file.sep, fixed = TRUE)[[1L]]) {
    stop("Graphical-abstract run root is not scoped beneath HFMD_RUN_ID")
  }
  summary_path <- path_inside_run_root(summary_path, run_root, must_work = TRUE)
  output_parent <- normalizePath(dirname(output_dir), mustWork = TRUE)
  if (!startsWith(output_parent, paste0(run_root, .Platform$file.sep)) && output_parent != run_root) {
    stop("Graphical-abstract output parent is outside the run staging root")
  }
  dir.create(output_dir, recursive = FALSE, showWarnings = FALSE, mode = "0700")
  output_dir <- path_inside_run_root(output_dir, run_root, must_work = TRUE)

  summary <- data.table::fread(summary_path, na.strings = c("", "NA"))
  missing <- setdiff(graphical_abstract_contract_columns, names(summary))
  if (length(missing)) stop("Graphical-abstract summary lacks: ", paste(missing, collapse = ", "))
  observed_run_ids <- unique(as.character(summary$run_id))
  if (length(observed_run_ids) != 1L || observed_run_ids[[1L]] != run_id) {
    stop("Graphical-abstract summary run_id mismatch")
  }
  parent_hashes <- unique(as.character(summary$parent_manifest_sha256))
  if (length(parent_hashes) != 1L || !grepl("^[0-9a-f]{64}$", parent_hashes[[1L]])) {
    stop("Graphical-abstract summary must bind one parent manifest SHA-256")
  }
  profiles <- unique(tolower(as.character(summary$profile)))
  if (length(profiles) != 1L || !profiles[[1L]] %in% c("ci", "synthetic", "restricted")) {
    stop("Graphical-abstract summary has an invalid profile")
  }
  environment_profile <- tolower(Sys.getenv("HFMD_PROFILE", unset = ""))
  if (nzchar(environment_profile) && environment_profile != profiles[[1L]]) {
    stop("HFMD_PROFILE does not match the graphical-abstract summary")
  }
  if (identical(profiles[[1L]], "restricted") &&
      !nzchar(Sys.getenv("HFMD_VISUAL_CONTRACT", unset = ""))) {
    stop("Restricted graphical-abstract rendering requires the run-scoped HFMD_VISUAL_CONTRACT snapshot")
  }
  visual_contract_path <- visual_contract_for_render(root)
  render_visual_contract <- read_hfmd_visual_contract(visual_contract_path)
  allowed_status <- c("pass", "stable", "conditional", "downgraded", "fail", "not_evaluated")
  unknown_status <- setdiff(unique(as.character(summary$gate_status)), allowed_status)
  if (length(unknown_status)) stop("Unknown graphical-abstract gate status: ", paste(unknown_status, collapse = ", "))
  if (nrow(summary) < 3L || nrow(summary) > 6L) {
    stop("Graphical-abstract summary must contain three to six ordered evidence layers")
  }
  if (anyDuplicated(summary$display_order) || anyDuplicated(summary$evidence_layer)) {
    stop("Graphical-abstract evidence layers and display_order values must be unique")
  }
  data.table::setorder(summary, display_order)
  summary[, `:=`(
    estimate = as.numeric(estimate),
    interval_low = as.numeric(interval_low),
    interval_high = as.numeric(interval_high)
  )]
  summary[, value_label := ifelse(
    is.finite(estimate),
    paste0(
      format_direct_number(estimate, 0.01),
      ifelse(is.finite(interval_low) & is.finite(interval_high),
             paste0(" [", format_direct_number(interval_low, 0.01), "–", format_direct_number(interval_high, 0.01), "]"), ""),
      ifelse(nzchar(unit), paste0(" ", unit), "")
    ),
    "Not estimated"
  )]

  n <- nrow(summary)
  summary[, x := seq(1.55, 8.85, length.out = n)]
  summary[, `:=`(xmin = x - 0.63, xmax = x + 0.63, ymin = 0.86, ymax = 2.22)]
  gate_colours <- c(
    pass = hfmd_palette[["teal"]], stable = hfmd_palette[["navy"]],
    conditional = hfmd_palette[["cream"]], downgraded = hfmd_palette[["orange"]],
    fail = hfmd_palette[["red"]], not_evaluated = hfmd_palette[["light"]]
  )
  arrows <- if (n > 1L) summary[seq_len(n - 1L), .(
    x = xmax, xend = summary$xmin[seq_len(n - 1L) + 1L], y = 1.54, yend = 1.54
  )] else NULL

  graphic <- ggplot() +
    geom_segment(
      data = arrows, aes(x = x, xend = xend, y = y, yend = yend),
      linewidth = 0.55, colour = hfmd_palette[["ink"]],
      arrow = grid::arrow(length = grid::unit(1.7, "mm"), type = "closed")
    ) +
    geom_rect(
      data = summary,
      aes(xmin = xmin, xmax = xmax, ymin = ymin, ymax = ymax, fill = gate_status),
      colour = hfmd_palette[["ink"]], linewidth = 0.45, alpha = 0.88
    ) +
    geom_text(
      data = summary, aes(x = x, y = 1.92, label = label),
      family = hfmd_font_family, fontface = "bold", size = 2.45, lineheight = 0.95
    ) +
    geom_text(
      data = summary, aes(x = x, y = 1.45, label = value_label),
      family = hfmd_font_family, size = 2.15, lineheight = 0.95
    ) +
    geom_text(
      data = summary, aes(x = x, y = 1.05, label = toupper(gate_status)),
      family = hfmd_font_family, size = 1.8, colour = hfmd_palette[["ink"]]
    ) +
    scale_fill_manual(values = gate_colours, guide = "none") +
    coord_cartesian(xlim = c(0.65, 9.75), ylim = c(0.42, 2.72), clip = "off") +
    theme_hfmd_void() +
    labs(title = "EV-A71 vaccination and multiscale HFMD community balance") +
    theme(
      plot.title = element_text(
        family = hfmd_font_family, face = "bold", size = 10,
        hjust = 0.5, colour = hfmd_palette[["navy"]], margin = margin(b = 8)
      )
    )

  synthetic <- profiles[[1L]] %in% c("ci", "synthetic")
  if (synthetic) {
    graphic <- graphic +
      annotate(
        "label", x = 5.2, y = 2.58,
        label = "SYNTHETIC VALIDATION — NOT FOR SCIENTIFIC INFERENCE",
        family = hfmd_font_family, fontface = "bold", size = 2.7,
        colour = hfmd_palette[["red"]], fill = "white", linewidth = 0.3
      )
  }

  outputs <- c(
    pdf = file.path(output_dir, "graphical_abstract.pdf"),
    svg = file.path(output_dir, "graphical_abstract.svg")
  )
  if (any(file.exists(outputs))) stop("Graphical-abstract renderer refuses to replace existing outputs")
  with_graphics_device(
    function() grDevices::cairo_pdf(outputs[["pdf"]], width = 7.2, height = 3.45, family = hfmd_font_family, bg = "white"),
    graphic
  )
  with_graphics_device(
    function() grDevices::svg(outputs[["svg"]], width = 7.2, height = 3.45, family = hfmd_font_family, bg = "white", onefile = TRUE),
    graphic
  )
  Sys.chmod(outputs, "0600")
  manifest <- data.table(
    file = basename(outputs),
    format = names(outputs),
    run_id = run_id,
    profile = profiles[[1L]],
    synthetic_validation = synthetic,
    parent_manifest_sha256 = parent_hashes[[1L]],
    summary_sha256 = sha256_file(summary_path),
    visual_contract_source_sha256 = render_visual_contract$source_sha256,
    visual_contract_resource_sha256 = render_visual_contract$resource_sha256,
    bytes = as.numeric(file.info(outputs)$size),
    sha256 = vapply(outputs, sha256_file, character(1))
  )
  manifest_path <- file.path(output_dir, "graphical_abstract_manifest.csv")
  data.table::fwrite(manifest, manifest_path)
  Sys.chmod(manifest_path, "0600")
  invisible(manifest)
}

if (sys.nframe() == 0L) {
  all_args <- commandArgs(trailingOnly = FALSE)
  script_arg <- grep("^--file=", all_args, value = TRUE)
  if (!length(script_arg)) stop("Unable to locate render_graphical_abstract.R")
  script_path <- normalizePath(sub("^--file=", "", script_arg[[1L]]), mustWork = TRUE)
  root <- normalizePath(file.path(dirname(script_path), ".."), mustWork = TRUE)
  args <- commandArgs(trailingOnly = TRUE)
  if (length(args) != 3L) {
    stop("Usage: Rscript Script_r/render_graphical_abstract.R RUN_ROOT GATED_SUMMARY_CSV OUTPUT_DIR")
  }
  render_graphical_abstract(root, args[[1L]], args[[2L]], args[[3L]])
  message("Rendered code-only graphical abstract as SVG/PDF")
}
