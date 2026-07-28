# Figure S4: vaccine-coverage proxy --------
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

# load vaccine-proxy trajectories --------
# Implemented ecological vaccine-coverage proxy by age.
weekly <- read_figure_data(
  file.path(result_dir, "weekly_input_summary.csv.gz"),
  c("week_start", "age_group", "vaccine_coverage_proxy_r00")
)
weekly[, week_start := as.Date(week_start)]
weekly[, age := factor(age_group, levels = age_order, labels = unname(age_labels[age_order]))]
# draw supplementary panel --------
figureS4 <- ggplot(weekly, aes(x = week_start, y = vaccine_coverage_proxy_r00, colour = age)) +
  geom_vline(xintercept = as.Date("2017-01-01"), linetype = "22", colour = hfmd_palette[["mid"]], linewidth = 0.45) +
  geom_line(linewidth = 0.65, lineend = "round") +
  scale_colour_manual(values = age_colours, drop = FALSE) +
  scale_x_date(date_breaks = "3 years", date_labels = "%Y", expand = expansion(mult = c(0.01, 0.01))) +
  scale_y_continuous(labels = scales::label_percent(accuracy = 1), expand = expansion(mult = c(0.02, 0.08))) +
  labs(x = "Calendar year", y = "Estimated ecological vaccine coverage")
# save figure --------
save_figure_bundle(figureS4, output_dir, "figureS4_vaccine_proxy", 7.2, 4.2)
write_figure_manifest(output_dir)
message("Rendered Figure S4: ", output_dir)
