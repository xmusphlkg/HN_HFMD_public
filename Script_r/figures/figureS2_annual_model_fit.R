# Figure S2: annual model fit --------
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

# load and aggregate fitted data --------
# Annual reconstructed proxy versus conditional model mean.
fit <- read_figure_data(
  file.path(result_dir, "fitted_week_age_pathogen.csv.gz"),
  c("week_start", "pathogen_group", "reported_pathogen_proxy", "conditional_expected_reported_cases")
)
fit[, year := as.integer(substr(week_start, 1, 4))]
annual <- fit[, .(
  reconstructed = sum(reported_pathogen_proxy),
  conditional = sum(conditional_expected_reported_cases)
), by = .(year, pathogen_group)]
annual[, pathogen := factor(pathogen_group, levels = names(pathogen_labels), labels = unname(pathogen_labels))]
# draw supplementary panel --------
figureS2 <- ggplot(annual, aes(x = year)) +
  annotate("rect", xmin = 2009.5, xmax = 2011.5, ymin = -Inf, ymax = Inf, fill = hfmd_palette[["cream"]], alpha = 0.28) +
  geom_line(aes(y = reconstructed, colour = pathogen_group), linewidth = 0.68) +
  geom_point(aes(y = reconstructed, colour = pathogen_group), size = 1.25) +
  geom_line(aes(y = conditional), colour = hfmd_palette[["ink"]], linewidth = 0.52, linetype = "22") +
  geom_point(aes(y = conditional), shape = 21, fill = "white", colour = hfmd_palette[["ink"]], size = 1.2, stroke = 0.38) +
  facet_grid(pathogen ~ ., scales = "free_y") +
  scale_colour_manual(values = pathogen_colours, guide = "none") +
  scale_x_continuous(breaks = c(2010, 2013, 2016, 2019, 2022, 2025), expand = expansion(mult = c(0.01, 0.01))) +
  scale_y_continuous(labels = scales::label_comma()) +
  labs(x = "Calendar year", y = "Estimated annual reported-case proxies")
# save figure --------
save_figure_bundle(figureS2, output_dir, "figureS2_annual_model_fit", 7.2, 5.2)
write_figure_manifest(output_dir)
message("Rendered Figure S2: ", output_dir)
