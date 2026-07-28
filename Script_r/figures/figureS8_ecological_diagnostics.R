# Figure S8: ecological model diagnostics --------
# Reads only the run-scoped ecological-diagnostic figure contract.

project_root <- normalizePath(getOption("hfmd.project_root", "."), mustWork = TRUE)
if (!file.exists(file.path(project_root, "HFMD.Rproj"))) stop("Set the working directory to the project root before sourcing this figure")
.libPaths(c(file.path(project_root, ".r_library"), .libPaths()))
source(file.path(project_root, "Script_r", "common.R"), local = FALSE)
result_dir <- hfmd_run_scoped_result_dir()
output_dir <- normalizePath(getOption("hfmd.output_dir"), mustWork = FALSE)
invalidate_figure_render_success()

diagnostics <- read_run_scoped_figure_contract(
  result_dir,
  "figureS8_ecological_diagnostics.csv",
  c(
    "panel", "model_id", "model_group", "diagnostic", "label", "x", "y",
    "estimate", "threshold", "status", "display_order"
  )
)
require_figure_panels(diagnostics, letters[1:4], "figureS8_ecological_diagnostics.csv")
diagnostics[, `:=`(
  panel = as.character(panel), x = as.numeric(x), y = as.numeric(y),
  estimate = as.numeric(estimate), threshold = as.numeric(threshold),
  display_order = as.numeric(display_order), status = as.character(status)
)]
unknown_status <- setdiff(unique(diagnostics$status), names(hfmd_status_colours))
if (length(unknown_status)) stop("Unregistered Figure S8 status values: ", paste(unknown_status, collapse = ", "))

p_a <- ggplot(diagnostics[panel == "a"], aes(x = x, y = y, colour = status)) +
  geom_hline(yintercept = 0, colour = hfmd_palette[["mid"]], linewidth = 0.35, linetype = "22") +
  geom_point(size = 1.35, alpha = 0.75) +
  scale_colour_manual(values = hfmd_status_colours, drop = FALSE, name = "Diagnostic status") +
  labs(x = "Fitted value", y = "Standardized residual") +
  theme_hfmd_legend(position = "bottom")

dispersion <- data.table::copy(diagnostics[panel == "b"])
data.table::setorder(dispersion, display_order, model_id)
dispersion[, label := factor(label, levels = unique(label))]
p_b <- ggplot(dispersion, aes(x = label, y = estimate, colour = status)) +
  geom_hline(
    data = unique(dispersion[, .(threshold)]), aes(yintercept = threshold),
    inherit.aes = FALSE, colour = hfmd_palette[["mid"]], linetype = "22", linewidth = 0.35
  ) +
  geom_point(size = 1.5) +
  scale_colour_manual(values = hfmd_status_colours, drop = FALSE, name = "Diagnostic status") +
  labs(x = NULL, y = "Dispersion diagnostic") +
  theme_hfmd_rotated_x(angle = 35) +
  theme_hfmd_legend(position = "bottom")

influence <- data.table::copy(diagnostics[panel == "c"])
data.table::setorder(influence, display_order, model_id)
influence[, label := factor(label, levels = rev(unique(label)))]
p_c <- ggplot(influence, aes(x = estimate, y = label, colour = status)) +
  geom_vline(
    data = unique(influence[, .(threshold)]), aes(xintercept = threshold),
    inherit.aes = FALSE, colour = hfmd_palette[["mid"]], linetype = "22", linewidth = 0.35
  ) +
  geom_segment(aes(x = 0, xend = estimate, yend = label), linewidth = 0.45) +
  geom_point(size = 1.5) +
  scale_colour_manual(values = hfmd_status_colours, drop = FALSE, name = "Diagnostic status") +
  labs(x = "Influence diagnostic", y = NULL) +
  theme_hfmd_legend(position = "bottom") +
  theme(axis.text.y = element_text(size = hfmd_axis_text_dense_size))

registry <- data.table::copy(diagnostics[panel == "d"])
data.table::setorder(registry, display_order, model_id)
registry[, model_id := factor(model_id, levels = rev(unique(model_id)))]
p_d <- ggplot(registry, aes(x = model_group, y = model_id, fill = status)) +
  geom_tile(colour = "white", linewidth = 0.25) +
  scale_fill_manual(values = hfmd_status_colours, drop = FALSE, name = "Model status") +
  labs(x = "Registered model group", y = "Registered model") +
  theme_hfmd_matrix(border = TRUE) +
  theme_hfmd_rotated_x(angle = 30) +
  theme_hfmd_legend(position = "bottom") +
  theme(axis.text.y = element_text(size = 3.8))

figureS8 <- (add_panel_tag(p_a, "a") | add_panel_tag(p_b, "b")) /
  (add_panel_tag(p_c, "c") | add_panel_tag(p_d, "d")) +
  plot_layout(heights = c(0.9, 1.45), guides = "collect") &
  theme(legend.position = "bottom")

save_figure_bundle(figureS8, output_dir, "figureS8_ecological_diagnostics")
write_figure_manifest(output_dir)
message("Rendered Figure S8 from its run-scoped contract: ", output_dir)
