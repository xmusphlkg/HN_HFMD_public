# Figure 2: county ecological effects and specification stability --------
# Reads only the run-scoped figure-data contract produced for this run.

project_root <- normalizePath(getOption("hfmd.project_root", "."), mustWork = TRUE)
if (!file.exists(file.path(project_root, "HFMD.Rproj"))) {
  stop("Set the working directory to the project root before sourcing this figure")
}
.libPaths(c(file.path(project_root, ".r_library"), .libPaths()))
source(file.path(project_root, "Script_r", "common.R"), local = FALSE)
result_dir <- hfmd_run_scoped_result_dir()
output_dir <- normalizePath(
  getOption("hfmd.output_dir", file.path(project_root, "Outcome", "figures", "main")),
  mustWork = FALSE
)
unlink(file.path(output_dir, "render_success.json"))

# load the registered, run-bound long-form contract --------
county <- read_run_scoped_figure_contract(
  result_dir,
  "figure2_county_ecological_effects.csv",
  c(
    "panel", "model_id", "model_group", "outcome", "estimand",
    "specification", "effect_scale", "estimate", "interval_low",
    "interval_high", "null_value", "status", "display_order"
  )
)
require_figure_panels(county, letters[1:5], "figure2_county_ecological_effects.csv")
county[, panel := as.character(panel)]
county[, display_order := as.numeric(display_order)]
county[, `:=`(
  estimate = as.numeric(estimate),
  interval_low = as.numeric(interval_low),
  interval_high = as.numeric(interval_high),
  null_value = as.numeric(null_value),
  status = as.character(status)
)]
unknown_status <- setdiff(unique(county$status), names(hfmd_status_colours))
if (length(unknown_status)) stop("Unregistered Figure 2 status values: ", paste(unknown_status, collapse = ", "))
if (any(!is.finite(county$estimate)) || any(!is.finite(county$null_value))) {
  stop("Figure 2 contract contains non-finite estimates or null values")
}
if (any(county$interval_low > county$estimate, na.rm = TRUE) ||
    any(county$interval_high < county$estimate, na.rm = TRUE)) {
  stop("Figure 2 intervals do not contain their point estimates")
}

forest_panel <- function(value, axis_title) {
  value <- data.table::copy(value)
  data.table::setorder(value, display_order, model_id)
  value[, display_label := ifelse(nzchar(estimand), estimand, outcome)]
  value[, display_label := factor(display_label, levels = rev(unique(display_label)))]
  reference <- unique(value[, .(effect_scale, null_value)])
  ggplot(value, aes(x = estimate, y = display_label, colour = status)) +
    geom_vline(
      data = reference, aes(xintercept = null_value), inherit.aes = FALSE,
      colour = hfmd_palette[["mid"]], linewidth = 0.35, linetype = "22"
    ) +
    geom_errorbarh(
      aes(xmin = interval_low, xmax = interval_high),
      height = 0, linewidth = 0.55, na.rm = TRUE
    ) +
    geom_point(size = 1.65, stroke = 0) +
    facet_grid(effect_scale ~ ., scales = "free", space = "free") +
    scale_colour_manual(values = hfmd_status_colours, drop = FALSE, name = "Registered status") +
    labs(x = axis_title, y = NULL) +
    theme_hfmd_legend(position = "bottom") +
    theme(
      strip.text.y = element_text(angle = 0, size = hfmd_strip_text_dense_size),
      axis.text.y = element_text(size = hfmd_axis_text_compact_size)
    )
}

status_matrix_panel <- function(value, x_title, y_title) {
  value <- data.table::copy(value)
  data.table::setorder(value, display_order, model_id)
  value[, outcome_label := factor(outcome, levels = rev(unique(outcome)))]
  value[, specification_label := factor(specification, levels = unique(specification))]
  ggplot(value, aes(x = specification_label, y = outcome_label, fill = status)) +
    geom_tile(colour = "white", linewidth = 0.5) +
    geom_text(
      aes(label = ifelse(is.finite(estimate), format_direct_number(estimate, 0.01), "")),
      family = hfmd_font_family, size = 1.9, colour = hfmd_palette[["ink"]]
    ) +
    scale_fill_manual(values = hfmd_status_colours, drop = FALSE, name = "Registered status") +
    labs(x = x_title, y = y_title) +
    theme_hfmd_matrix(border = TRUE) +
    theme_hfmd_rotated_x(angle = 30) +
    theme_hfmd_legend(position = "bottom") +
    theme(axis.text = element_text(size = hfmd_axis_text_dense_size))
}

# panel a is the primary-estimand hero; b-e preserve the registered evidence layers --------
p_a <- add_panel_tag(
  forest_panel(county[panel == "a"], "Estimate on the registered native scale (95% interval)"),
  "a"
)
p_b <- add_panel_tag(
  forest_panel(county[panel == "b"], "Mechanism-secondary estimate (95% interval)"),
  "b"
)
p_c <- add_panel_tag(
  status_matrix_panel(county[panel == "c"], "Prespecified specification", "Outcome"),
  "c"
)
p_d <- add_panel_tag(
  forest_panel(county[panel == "d"], "Typing-selection/restriction estimate (95% interval)"),
  "d"
)
p_e <- add_panel_tag(
  status_matrix_panel(county[panel == "e"], "Inferential boundary", "Estimand"),
  "e"
)

figure2 <- p_a / (p_b | p_c) / (p_d | p_e) +
  plot_layout(heights = c(1.55, 1.0, 1.0), guides = "collect") &
  theme(legend.position = "bottom")

save_figure_bundle(figure2, output_dir, "figure2_county_ecological_effects")
write_figure_manifest(output_dir)
message("Rendered Figure 2 from its run-scoped contract: ", output_dir)
