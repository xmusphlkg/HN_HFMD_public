# Figure S5: bootstrap estimands --------
# Canonical supplementary-figure script; edit this file to change this figure only.

project_root <- normalizePath(getOption("hfmd.project_root", "."), mustWork = TRUE)
if (!file.exists(file.path(project_root, "HFMD.Rproj"))) stop("Set the working directory to the project root before sourcing this figure")
.libPaths(c(file.path(project_root, ".r_library"), .libPaths()))
source(file.path(project_root, "Script_r", "common.R"), local = FALSE)
result_dir <- normalizePath(
  getOption("hfmd.result_dir", file.path(project_root, "AnalysisOutput", "transmission_dynamics")),
  mustWork = TRUE
)
output_dir <- normalizePath(
  getOption("hfmd.output_dir", file.path(project_root, "Outcome", "figures", "supplementary")),
  mustWork = FALSE
)
invalidate_figure_render_success()

# load bootstrap distributions --------
# Structural uncertainty is shown separately in Figure 4e.
bootstrap <- read_figure_data(
  file.path(result_dir, "bootstrap_counterfactual_metrics.csv"),
  c("replicate", "scope", "estimand", "estimate")
)
keep_estimands <- c(
  ev_a71_reported_cases_averted = "EV-A71 proxies averted",
  non_ev_competitive_release_cases = "Additional non-EV-A71 proxies",
  net_all_pathogen_reported_cases_averted = "Net proxies averted"
)
bootstrap <- bootstrap[scope == "all_ages" & estimand %in% names(keep_estimands)]
bootstrap[, panel := factor(estimand, levels = names(keep_estimands), labels = unname(keep_estimands))]
# draw bootstrap panels --------
bootstrap_medians <- bootstrap[, .(median = median(estimate)), by = panel]
figureS5_panels <- lapply(seq_along(keep_estimands), function(index) {
  label <- unname(keep_estimands)[[index]]
  panel_data <- bootstrap[panel == label]
  median_value <- bootstrap_medians[panel == label, median]
  ggplot(panel_data, aes(x = estimate)) +
    geom_histogram(bins = 18, fill = hfmd_palette[["pale_teal"]], colour = "white", linewidth = 0.25) +
    geom_vline(xintercept = median_value, colour = hfmd_palette[["orange"]], linewidth = 0.65) +
    scale_x_continuous(labels = scales::label_comma()) +
    labs(x = "Estimated reported-case proxies", y = "Bootstrap replicates") +
    theme_hfmd_rotated_x(angle = 30)
})
figureS5 <- wrap_plots(figureS5_panels, nrow = 1) +
  plot_layout(tag_level = "new") +
  plot_annotation(tag_levels = "a")
# save figure --------
save_figure_bundle(figureS5, output_dir, "figureS5_bootstrap_estimands", 7.2, 3.55)
write_figure_manifest(output_dir)
message("Rendered Figure S5: ", output_dir)
