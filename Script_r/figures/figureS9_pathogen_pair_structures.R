# Figure S9: pathogen-pair interaction structures --------
# Reads only the run-scoped structure-comparison figure contract.

project_root <- normalizePath(getOption("hfmd.project_root", "."), mustWork = TRUE)
if (!file.exists(file.path(project_root, "HFMD.Rproj"))) stop("Set the working directory to the project root before sourcing this figure")
.libPaths(c(file.path(project_root, ".r_library"), .libPaths()))
source(file.path(project_root, "Script_r", "common.R"), local = FALSE)
result_dir <- hfmd_run_scoped_result_dir()
output_dir <- normalizePath(getOption("hfmd.output_dir"), mustWork = FALSE)
invalidate_figure_render_success()

structures <- read_run_scoped_figure_contract(
  result_dir,
  "figureS9_pathogen_pair_structures.csv",
  c(
    "panel", "model_id", "pathogen_pair", "direction", "fold", "component",
    "metric", "estimate", "interval_low", "interval_high", "null_value",
    "boundary_distance", "status", "display_order"
  )
)
require_figure_panels(structures, letters[1:4], "figureS9_pathogen_pair_structures.csv")
structures[, `:=`(
  panel = as.character(panel), fold = as.numeric(fold), estimate = as.numeric(estimate),
  interval_low = as.numeric(interval_low), interval_high = as.numeric(interval_high),
  null_value = as.numeric(null_value), boundary_distance = as.numeric(boundary_distance),
  display_order = as.numeric(display_order), status = as.character(status)
)]
unknown_status <- setdiff(unique(structures$status), names(hfmd_status_colours))
if (length(unknown_status)) stop("Unregistered Figure S9 status values: ", paste(unknown_status, collapse = ", "))

comparison <- data.table::copy(structures[panel == "a"])
data.table::setorder(comparison, display_order, model_id)
comparison[, model_id := factor(model_id, levels = rev(unique(model_id)))]
p_a <- ggplot(comparison, aes(x = estimate, y = model_id, colour = status)) +
  geom_vline(xintercept = 0, colour = hfmd_palette[["mid"]], linewidth = 0.35, linetype = "22") +
  geom_errorbarh(aes(xmin = interval_low, xmax = interval_high), height = 0, linewidth = 0.55, na.rm = TRUE) +
  geom_point(size = 1.6) +
  facet_grid(metric ~ ., scales = "free", space = "free") +
  scale_colour_manual(values = hfmd_status_colours, drop = FALSE, name = "Registered status") +
  labs(x = "Rolling-score difference from paired no-interaction model", y = NULL) +
  theme_hfmd_legend(position = "bottom")

directional <- data.table::copy(structures[panel == "b"])
data.table::setorder(directional, display_order, pathogen_pair, direction)
directional[, pair_direction := factor(
  paste(pathogen_pair, direction, sep = " → "),
  levels = rev(unique(paste(pathogen_pair, direction, sep = " → ")))
)]
references <- unique(directional[, .(metric, null_value)])
p_b <- ggplot(directional, aes(x = estimate, y = pair_direction, colour = status)) +
  geom_vline(
    data = references, aes(xintercept = null_value), inherit.aes = FALSE,
    colour = hfmd_palette[["mid"]], linewidth = 0.35, linetype = "22"
  ) +
  geom_errorbarh(aes(xmin = interval_low, xmax = interval_high), height = 0, linewidth = 0.55, na.rm = TRUE) +
  geom_point(size = 1.6) +
  facet_grid(metric ~ ., scales = "free", space = "free") +
  scale_colour_manual(values = hfmd_status_colours, drop = FALSE, name = "Registered status") +
  labs(x = "Directional parameter (95% interval)", y = NULL) +
  theme_hfmd_legend(position = "bottom") +
  theme(axis.text.y = element_text(size = hfmd_axis_text_dense_size))

boundaries <- data.table::copy(structures[panel == "c"])
data.table::setorder(boundaries, display_order, model_id)
boundaries[, label := factor(paste(model_id, pathogen_pair, sep = " | "), levels = rev(unique(paste(model_id, pathogen_pair, sep = " | "))))]
p_c <- ggplot(boundaries, aes(x = boundary_distance, y = label, colour = status)) +
  geom_vline(xintercept = 0, colour = hfmd_palette[["red"]], linewidth = 0.4) +
  geom_segment(aes(x = 0, xend = boundary_distance, yend = label), linewidth = 0.45) +
  geom_point(size = 1.55) +
  scale_colour_manual(values = hfmd_status_colours, drop = FALSE, name = "Boundary status") +
  labs(x = "Distance from nearest registered parameter boundary", y = NULL) +
  theme_hfmd_legend(position = "bottom") +
  theme(axis.text.y = element_text(size = hfmd_axis_text_dense_size))

folds <- data.table::copy(structures[panel == "d"])
p_d <- ggplot(folds, aes(x = fold, y = estimate, colour = component, group = component)) +
  geom_hline(yintercept = 0, colour = hfmd_palette[["mid"]], linewidth = 0.35, linetype = "22") +
  geom_line(linewidth = 0.65) +
  geom_point(size = 1.35) +
  scale_colour_manual(
    values = c(joint = hfmd_palette[["navy"]], total_cases = hfmd_palette[["orange"]], typing = hfmd_palette[["teal"]]),
    name = "Log-score component"
  ) +
  scale_x_continuous(breaks = sort(unique(folds$fold))) +
  facet_wrap(~model_id, scales = "free_y") +
  labs(x = "Rolling-origin fold", y = "Log-score difference from M1") +
  theme_hfmd_legend(position = "bottom")

figureS9 <- (add_panel_tag(p_a, "a") | add_panel_tag(p_b, "b")) /
  (add_panel_tag(p_c, "c") | add_panel_tag(p_d, "d")) +
  plot_layout(heights = c(1.05, 1.0), guides = "collect") &
  theme(legend.position = "bottom")

save_figure_bundle(figureS9, output_dir, "figureS9_pathogen_pair_structures")
write_figure_manifest(output_dir)
message("Rendered Figure S9 from its run-scoped contract: ", output_dir)
