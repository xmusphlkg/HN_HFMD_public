# Figure S7: pathogen-typing diagnostics --------
# Monitoring summaries moved from Figure 1 to keep the main figure compact.

project_root <- normalizePath(getOption("hfmd.project_root", "."), mustWork = TRUE)
if (!file.exists(file.path(project_root, "HFMD.Rproj"))) stop("Set the working directory to the project root before sourcing this figure")
.libPaths(c(file.path(project_root, ".r_library"), .libPaths()))
source(file.path(project_root, "Script_r", "common.R"), local = FALSE)
result_dir <- normalizePath(getOption("hfmd.result_dir", file.path(project_root, "AnalysisOutput", "transmission_dynamics")), mustWork = TRUE)
output_dir <- normalizePath(getOption("hfmd.output_dir", file.path(project_root, "Outcome", "figures", "supplementary")), mustWork = FALSE)
invalidate_figure_render_success()

fit <- read_figure_data(
  file.path(result_dir, "fitted_week_age_pathogen.csv.gz"),
  c("age_group", "pathogen_group", "typed_cases")
)
weekly_inputs <- read_figure_data(
  file.path(result_dir, "weekly_input_summary.csv.gz"),
  c("week_start", "typed_cases")
)
weekly_inputs[, year := as.integer(substr(week_start, 1, 4))]
annual_surveillance <- weekly_inputs[, .(typed = sum(typed_cases)), by = year]

pS7a <- ggplot(annual_surveillance, aes(x = year, y = typed)) +
  geom_col(width = 0.72, fill = hfmd_palette[["navy"]]) +
  geom_text(
    data = annual_surveillance[year %in% c(2010, 2017, 2020, 2025)],
    aes(label = scales::comma(typed)), vjust = -0.35,
    family = hfmd_font_family, size = 2.1
  ) +
  scale_x_continuous(breaks = c(2010, 2015, 2020, 2025)) +
  scale_y_continuous(labels = scales::label_comma(), expand = expansion(mult = c(0, 0.16))) +
  labs(x = "Calendar year", y = "Specimens with pathogen typing")

typed_age_pathogen <- fit[, .(typed = sum(typed_cases)), by = .(age_group, pathogen_group)]
typed_age_pathogen[, age := factor(age_group, levels = age_order, labels = unname(age_labels[age_order]))]
pS7b <- ggplot(typed_age_pathogen, aes(x = age, y = typed, fill = pathogen_group)) +
  geom_col(position = "fill", width = 0.70) +
  scale_fill_manual(values = pathogen_colours, labels = pathogen_labels, name = "Pathogen") +
  scale_y_continuous(labels = scales::label_percent(accuracy = 1), expand = c(0, 0)) +
  labs(x = "Age group (years)", y = "Distribution among typed specimens")

figureS7 <- pS7a + pS7b +
  plot_layout(widths = c(0.92, 1.08), guides = "keep") +
  plot_annotation(tag_levels = "a")

save_figure_bundle(figureS7, output_dir, "figureS7_typing_diagnostics", 7.2, 3.6)
write_figure_manifest(output_dir)
message("Rendered Figure S7: ", output_dir)
