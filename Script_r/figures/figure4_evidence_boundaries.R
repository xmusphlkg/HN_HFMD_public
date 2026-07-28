# Figure 4: evidence boundaries --------
# Canonical main-figure script; edit this file to change this figure only.

project_root <- normalizePath(getOption("hfmd.project_root", "."), mustWork = TRUE)
if (!file.exists(file.path(project_root, "HFMD.Rproj"))) stop("Set the working directory to the project root before sourcing this figure")
.libPaths(c(file.path(project_root, ".r_library"), .libPaths()))
source(file.path(project_root, "Script_r", "common.R"), local = FALSE)
result_dir <- normalizePath(
  getOption("hfmd.result_dir", file.path(project_root, "AnalysisOutput", "transmission_dynamics")),
  mustWork = TRUE
)
output_dir <- normalizePath(
  getOption("hfmd.output_dir", file.path(project_root, "Outcome", "figures", "main")),
  mustWork = FALSE
)
unlink(file.path(output_dir, "render_success.json"))

# Figure-wide visual grammar follows Figures 1-3 --------
profile_breaks <- c(0, 0.2, 0.4, 0.6, 0.8, 0.96)
holdout_years <- as.Date(c("2023-01-01", "2024-01-01", "2025-01-01"))

# panel A: candidate-model mechanisms --------
# Candidate support, identifiability, structural uncertainty, and temporal
# validation define the evidentiary boundary of the main result.
model_comparison <- read_figure_data(
  file.path(result_dir, "model_comparison.csv"),
  c("candidate", "aic", "bic", "delta_aic", "converged")
)
model_labels <- c(
  M0_no_vaccine_no_cross = "M0\nNo vaccine / no heterotypic protection",
  M1_vaccine_no_cross = "M1\nVaccine only",
  M2_vaccine_cross = "M2\nVaccine + heterotypic protection",
  M3_vaccine_cross_no_covid = "M3\nNo pandemic multipliers",
  M4_vaccine_cross_weather = "M4\nWeather extension"
)
model_comparison[, `:=`(
  label = unname(model_labels[candidate]),
  delta_bic = bic - min(bic)
)]
# ggplot places the first discrete level at the bottom.  Reverse the intended
# reading order so panels A and B run from M0 at the top to M4 at the bottom.
model_row_order <- rev(unname(model_labels))
model_metrics <- melt(
  model_comparison,
  id.vars = c("candidate", "label"),
  measure.vars = c("delta_aic", "delta_bic"),
  variable.name = "metric", value.name = "delta"
)
model_metrics[, metric := factor(metric, levels = c("delta_aic", "delta_bic"), labels = c("Delta AIC", "Delta BIC"))]
model_metrics[, label := factor(label, levels = model_row_order)]
model_features <- data.table(
  candidate = rep(names(model_labels), each = 4),
  mechanism = rep(c("Vaccine", "Heterotypic\nprotection", "Pandemic-period\nadjustment", "Weather"), times = 5),
  included = c(
    FALSE, FALSE, TRUE, FALSE,
    TRUE, FALSE, TRUE, FALSE,
    TRUE, TRUE, TRUE, FALSE,
    TRUE, TRUE, FALSE, FALSE,
    TRUE, TRUE, TRUE, TRUE
  )
)
model_features[, `:=`(
  label = factor(unname(model_labels[candidate]), levels = model_row_order),
  mechanism = factor(mechanism, levels = c("Vaccine", "Heterotypic\nprotection", "Pandemic-period\nadjustment", "Weather"))
)]
p4a <- ggplot(model_features, aes(x = mechanism, y = label)) +
  geom_tile(fill = hfmd_palette[["faint"]], colour = "white", linewidth = 0.65) +
  geom_point(
    aes(fill = included), shape = 21, colour = hfmd_palette[["navy"]],
    stroke = 0.45, size = 2.5
  ) +
  scale_fill_manual(values = c(`TRUE` = hfmd_palette[["teal"]], `FALSE` = "white"), guide = "none") +
  labs(x = NULL, y = NULL) +
  theme_hfmd_matrix() +
  theme(
    axis.text.x = element_text(size = hfmd_axis_text_dense_size),
    axis.text.y = element_text(size = hfmd_axis_text_compact_size)
  )

# panel B: relative model support --------
p4b <- ggplot(model_metrics, aes(x = delta, y = label, colour = metric, shape = metric)) +
  annotate("rect", xmin = 0, xmax = 2, ymin = -Inf, ymax = Inf, fill = hfmd_palette[["cream"]], alpha = 0.30) +
  geom_vline(xintercept = 2, linetype = "22", colour = hfmd_palette[["mid"]], linewidth = 0.42) +
  geom_point(size = 2.25, position = position_dodge(width = 0.40)) +
  scale_colour_manual(values = c("Delta AIC" = hfmd_palette[["navy"]], "Delta BIC" = hfmd_palette[["teal"]])) +
  scale_shape_manual(values = c("Delta AIC" = 16, "Delta BIC" = 1)) +
  scale_x_continuous(
    breaks = c(0, 50, 100, 150, 200), limits = c(0, 225),
    labels = scales::label_number(accuracy = 1), expand = expansion(mult = c(0.03, 0))
  ) +
  labs(x = "Difference from best score", y = NULL) +
  theme(legend.direction = "horizontal") +
  theme_hfmd_legend(
    position = "inside", inside = c(1, 0.01), justification = c(1, 0),
    background_alpha = 0.90
  ) +
  guides(
    colour = guide_legend(
      title = "Information criterion", title.position = "top", nrow = 1, byrow = TRUE
    ),
    shape = guide_legend(
      title = "Information criterion", title.position = "top", nrow = 1, byrow = TRUE
    )
  )

# panels C-D: profile likelihood and release estimate --------
profile <- read_figure_data(
  file.path(result_dir, "profile_cross_strength.csv"),
  c("cross_strength", "delta_log_likelihood_from_main", "release_estimate", "converged")
)
full_fit <- jsonlite::fromJSON(file.path(result_dir, "fit_M2_vaccine_cross.json"))$derived$cross_strength
training_fit <- jsonlite::fromJSON(file.path(result_dir, "fit_M2_vaccine_cross_train_through_2022.json"))$derived$cross_strength
profile_vlines <- data.table(
  x = c(training_fit, full_fit),
  fit = c("Train through 2022", "Full period"),
  label_x = c(training_fit + 0.018, full_fit - 0.018),
  c_label_y = c(-2, -9),
  d_label_y = c(345, 315)
)
profile_colours <- c(`Train through 2022` = hfmd_palette[["mid"]], `Full period` = hfmd_palette[["red"]])
p4c <- ggplot(profile, aes(x = cross_strength, y = delta_log_likelihood_from_main)) +
  geom_hline(yintercept = 0, colour = hfmd_palette[["light"]], linewidth = 0.35) +
  geom_vline(data = profile_vlines, aes(xintercept = x, colour = fit), linetype = "22", linewidth = 0.42) +
  geom_text(
    data = profile_vlines,
    aes(x = label_x, y = c_label_y, label = fit, colour = fit),
    angle = 90, hjust = 1, vjust = 0.5, family = hfmd_font_family, size = 1.75,
    show.legend = FALSE
  ) +
  geom_line(colour = hfmd_palette[["navy"]], linewidth = 0.65) +
  geom_point(shape = 21, fill = hfmd_palette[["navy"]], colour = "white", size = 1.7, stroke = 0.35) +
  scale_colour_manual(values = profile_colours, guide = "none") +
  scale_x_continuous(breaks = profile_breaks, limits = c(0, 0.965), expand = c(0, 0)) +
  scale_y_continuous(breaks = c(-60, -40, -20, 0), limits = c(-60, 0.1), expand = c(0, 0)) +
  labs(
    x = "Fixed heterotypic-protection strength",
    y = "Profile log-likelihood difference\nrelative to the maximum"
  )
p4d <- ggplot(profile, aes(x = cross_strength, y = release_estimate)) +
  geom_hline(yintercept = 0, colour = hfmd_palette[["light"]], linewidth = 0.35) +
  geom_vline(data = profile_vlines, aes(xintercept = x, colour = fit), linetype = "22", linewidth = 0.42) +
  geom_text(
    data = profile_vlines,
    aes(x = label_x, y = d_label_y, label = fit, colour = fit),
    angle = 90, hjust = 1, vjust = 0.5, family = hfmd_font_family, size = 1.75,
    show.legend = FALSE
  ) +
  geom_line(colour = hfmd_palette[["teal"]], linewidth = 0.65) +
  geom_point(shape = 21, fill = hfmd_palette[["teal"]], colour = "white", size = 1.7, stroke = 0.35) +
  scale_colour_manual(values = profile_colours, guide = "none") +
  scale_x_continuous(breaks = profile_breaks, limits = c(0, 0.965), expand = c(0, 0)) +
  scale_y_continuous(
    breaks = c(0, 100, 200, 300), limits = c(0, 360),
    labels = scales::label_comma(), expand = c(0, 0)
  ) +
  labs(
    x = "Fixed heterotypic-protection strength",
    y = "Estimated additional non-EV-A71\nreported-case proxies"
  ) +
  theme(plot.margin = margin(7, 6, 5, 6))

# panel E: structural-sensitivity estimates --------
sensitivity <- read_figure_data(
  file.path(result_dir, "sensitivity_estimands.csv"),
  c("sensitivity", "scope", "estimand", "estimate", "converged")
)
sensitivity <- sensitivity[scope == "all_ages" & estimand == "non_ev_competitive_release_cases"]
sensitivity[, display_label := unname(sensitivity_display_labels[as.character(get("sensitivity"))])]
if (anyNA(sensitivity$display_label)) stop("A reader-facing sensitivity label is missing")
sensitivity[, display_label := factor(display_label, levels = display_label[order(estimate, decreasing = TRUE)])]
sensitivity[, assumption := fcase(
  grepl("^reporting_", sensitivity), "Reporting",
  grepl("^cross_", sensitivity), "Heterotypic protection",
  grepl("^homologous_|^generation_", sensitivity), "Natural history",
  grepl("^coverage_|^vaccine_", sensitivity), "Vaccine proxy",
  default = "Population / typing"
)]
assumption_colours <- c(
  "Reporting" = hfmd_palette[["red"]],
  "Heterotypic protection" = hfmd_palette[["teal"]],
  "Natural history" = hfmd_palette[["navy"]],
  "Vaccine proxy" = hfmd_palette[["orange"]],
  "Population / typing" = hfmd_palette[["blue"]]
)
estimands <- read_counterfactual_estimands(result_dir)
release_row <- estimands[
  scope == "all_ages" & estimand == "non_ev_competitive_release_cases"
]
main_release <- release_row$estimate
p4e <- ggplot(sensitivity, aes(x = estimate, y = display_label, fill = assumption)) +
  annotate(
    "rect", xmin = release_row$bootstrap_low, xmax = release_row$bootstrap_high,
    ymin = -Inf, ymax = Inf, fill = hfmd_palette[["cream"]], alpha = 0.34
  ) +
  geom_vline(xintercept = 0, linetype = "22", colour = hfmd_palette[["mid"]], linewidth = 0.36) +
  geom_vline(xintercept = main_release, linetype = "22", colour = hfmd_palette[["orange"]], linewidth = 0.42) +
  geom_point(shape = 21, size = 2.15, stroke = 0.38, colour = "white") +
  scale_fill_manual(values = assumption_colours, name = "Assumption varied") +
  scale_x_continuous(
    trans = scales::pseudo_log_trans(sigma = 50),
    breaks = c(0, 300, 1000, 5000), labels = scales::label_comma()
  ) +
  labs(x = "Additional non-EV-A71 reported-case proxies", y = NULL) +
  theme(axis.text.y = element_text(size = hfmd_axis_text_dense_size)) +
  theme_hfmd_legend(
    position = "inside", inside = c(1, 1), justification = c(1, 1),
    background_alpha = 0.90
  )

# panel F: temporal prediction boundary --------
holdout <- read_figure_data(
  file.path(result_dir, "holdout_predictions.csv"),
  c("week_start", "observed_cases", "conditional_expected", "recursive_expected")
)
holdout[, week_start := as.Date(week_start)]
holdout_sum <- holdout[, .(
  observed = sum(observed_cases),
  `Conditional one-step` = sum(conditional_expected),
  Recursive = sum(recursive_expected)
), by = week_start]
holdout_overlay <- rbindlist(list(
  holdout_sum[, .(week_start, series_label = "Observed", cases = observed)],
  holdout_sum[, .(week_start, series_label = "Calibrated one-step", cases = `Conditional one-step`)],
  holdout_sum[, .(week_start, series_label = "Recursive", cases = Recursive)]
))
holdout_overlay[, series_label := factor(
  series_label, levels = c("Observed", "Calibrated one-step", "Recursive")
)]
holdout_colours <- c(
  "Observed" = hfmd_palette[["ink"]],
  "Calibrated one-step" = hfmd_palette[["teal"]],
  "Recursive" = hfmd_palette[["red"]]
)
holdout_breaks <- c(0, 10, 100, 1000, 10000, 50000)
p4f <- ggplot(holdout_overlay, aes(x = week_start, y = cases, colour = series_label)) +
  geom_line(linewidth = 0.56, alpha = 0.90) +
  scale_colour_manual(values = holdout_colours, name = "Holdout series") +
  scale_x_date(
    breaks = holdout_years, date_labels = "%Y",
    limits = as.Date(c("2023-01-01", "2025-12-31")), expand = c(0, 0)
  ) +
  scale_y_continuous(
    transform = scales::transform_log1p(), breaks = holdout_breaks,
    limits = c(0, 50000), labels = scales::label_comma(), expand = c(0, 0)
  ) +
  labs(x = "Holdout week", y = "Age-aggregated weekly reported cases") +
  guides(colour = guide_legend(title.position = "top", ncol = 1, byrow = TRUE)) +
  theme_hfmd_legend(
    position = "inside", inside = c(1, 0.01), justification = c(1, 0),
    background_alpha = 0.90
  )

# assemble figure --------

design <- "
AC
BD
EF
"

figure4 <-
  p4a + p4b +
  p4c + p4d +
  p4e + p4f +
  plot_layout(
    ncol = 2, widths = c(1, 1), heights = c(0.72, 0.82, 1.68),
    guides = "keep", tag_level = "new", design = design
  ) +
  plot_annotation(tag_levels = "a")
# save figure --------
save_figure_bundle(figure4, output_dir, "figure4_evidence_boundaries", 7.2, 7.8)
write_figure_manifest(output_dir)
message("Rendered Figure 4: ", output_dir)
