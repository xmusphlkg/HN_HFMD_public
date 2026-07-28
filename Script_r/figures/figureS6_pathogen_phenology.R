# Figure S6: pathogen-specific phenology --------
# Canonical supplementary-figure script; moved from Figure 1 to retain the
# seasonal evidence without competing with the main surveillance narrative.

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

fit <- read_figure_data(
  file.path(result_dir, "fitted_week_age_pathogen.csv.gz"),
  c("week_start", "pathogen_group", "reported_pathogen_proxy")
)
fit[, week_start := as.Date(week_start)]
phenology <- fit[, .(
  estimated_cases = sum(reported_pathogen_proxy)
), by = .(
  pathogen_group,
  year = as.integer(format(week_start, "%Y")),
  epidemic_week = pmin(as.integer(format(week_start, "%V")), 52L)
)]
phenology[, intensity := frank(log1p(estimated_cases), ties.method = "average") / .N, by = pathogen_group]
phenology[, pathogen := factor(pathogen_group, levels = names(pathogen_labels), labels = unname(pathogen_labels))]

figureS6 <- ggplot(phenology, aes(x = epidemic_week, y = factor(year), fill = intensity)) +
  geom_tile(width = 1.02, height = 1.02) +
  facet_grid(pathogen ~ ., switch = "y") +
  scale_fill_gradientn(
    colours = hfmd_sequential_colours,
    breaks = c(0, 0.5, 1), labels = c("0", "50", "100"),
    name = "Within-pathogen weekly percentile"
  ) +
  scale_x_continuous(breaks = c(1, 13, 26, 39, 52), expand = c(0, 0)) +
  scale_y_discrete(breaks = as.character(c(2010, 2013, 2016, 2019, 2022, 2025))) +
  labs(x = "Epidemiological week", y = NULL) +
  theme_hfmd_matrix() +
  theme(
    strip.placement = "outside",
    strip.text.y.left = element_text(angle = 0, hjust = 1)
  )

save_figure_bundle(figureS6, output_dir, "figureS6_pathogen_phenology", 7.2, 5.2)
write_figure_manifest(output_dir)
message("Rendered Figure S6: ", output_dir)
