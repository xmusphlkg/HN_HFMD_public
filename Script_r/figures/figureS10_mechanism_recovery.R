# Figure S10: mechanism-recovery simulations --------
# Reads only the run-scoped simulation-operating-characteristic contract.

project_root <- normalizePath(getOption("hfmd.project_root", "."), mustWork = TRUE)
if (!file.exists(file.path(project_root, "HFMD.Rproj"))) stop("Set the working directory to the project root before sourcing this figure")
.libPaths(c(file.path(project_root, ".r_library"), .libPaths()))
source(file.path(project_root, "Script_r", "common.R"), local = FALSE)
result_dir <- hfmd_run_scoped_result_dir()
output_dir <- normalizePath(getOption("hfmd.output_dir"), mustWork = FALSE)
invalidate_figure_render_success()

recovery <- read_run_scoped_figure_contract(
  result_dir,
  "figureS10_mechanism_recovery.csv",
  c(
    "panel", "scenario", "mechanism", "metric", "estimate", "interval_low",
    "interval_high", "target", "status", "display_order"
  )
)
require_figure_panels(recovery, letters[1:4], "figureS10_mechanism_recovery.csv")
recovery[, `:=`(
  panel = as.character(panel), estimate = as.numeric(estimate),
  interval_low = as.numeric(interval_low), interval_high = as.numeric(interval_high),
  target = as.numeric(target), display_order = as.numeric(display_order),
  status = as.character(status)
)]
unknown_status <- setdiff(unique(recovery$status), names(hfmd_status_colours))
if (length(unknown_status)) stop("Unregistered Figure S10 status values: ", paste(unknown_status, collapse = ", "))

operating_point_panel <- function(value, y_title, reference = NULL, band = NULL) {
  value <- data.table::copy(value)
  data.table::setorder(value, display_order, scenario)
  value[, scenario := factor(scenario, levels = unique(scenario))]
  plot <- ggplot(value, aes(x = scenario, y = estimate, colour = status))
  if (!is.null(band)) {
    plot <- plot + annotate(
      "rect", xmin = -Inf, xmax = Inf, ymin = band[[1L]], ymax = band[[2L]],
      fill = hfmd_palette[["pale_teal"]], alpha = 0.22
    )
  }
  if (!is.null(reference)) {
    plot <- plot + geom_hline(
      yintercept = reference, colour = hfmd_palette[["mid"]],
      linewidth = 0.35, linetype = "22"
    )
  }
  plot +
    geom_errorbar(aes(ymin = interval_low, ymax = interval_high), width = 0, linewidth = 0.5, na.rm = TRUE) +
    geom_point(size = 1.55) +
    scale_colour_manual(values = hfmd_status_colours, drop = FALSE, name = "Recovery status") +
    labs(x = NULL, y = y_title) +
    theme_hfmd_rotated_x(angle = 32) +
    theme_hfmd_legend(position = "bottom")
}

p_a <- operating_point_panel(
  recovery[panel == "a"], "False-selection rate", reference = 0.05
)
p_b <- operating_point_panel(
  recovery[panel == "b"], "Relative bias", reference = 0
) +
  geom_hline(yintercept = c(-0.20, 0.20), colour = hfmd_palette[["orange"]], linewidth = 0.3, linetype = "22")
p_c <- operating_point_panel(
  recovery[panel == "c"], "95% interval coverage", reference = 0.95,
  band = c(0.90, 0.98)
)

summary_grid <- data.table::copy(recovery[panel == "d"])
data.table::setorder(summary_grid, display_order, scenario, metric)
summary_grid[, scenario := factor(scenario, levels = rev(unique(scenario)))]
p_d <- ggplot(summary_grid, aes(x = metric, y = scenario, fill = status)) +
  geom_tile(colour = "white", linewidth = 0.45) +
  geom_text(
    aes(label = format_direct_number(estimate, 0.01)),
    family = hfmd_font_family, size = 2.0, colour = hfmd_palette[["ink"]]
  ) +
  scale_fill_manual(values = hfmd_status_colours, drop = FALSE, name = "Recovery status") +
  labs(x = "Operating characteristic", y = "Data-generating scenario") +
  theme_hfmd_matrix(border = TRUE) +
  theme_hfmd_rotated_x(angle = 30) +
  theme_hfmd_legend(position = "bottom")

figureS10 <- (add_panel_tag(p_a, "a") | add_panel_tag(p_b, "b") | add_panel_tag(p_c, "c")) /
  add_panel_tag(p_d, "d") +
  plot_layout(heights = c(0.95, 1.15), guides = "collect") &
  theme(legend.position = "bottom")

save_figure_bundle(figureS10, output_dir, "figureS10_mechanism_recovery")
write_figure_manifest(output_dir)
message("Rendered Figure S10 from its run-scoped contract: ", output_dir)
