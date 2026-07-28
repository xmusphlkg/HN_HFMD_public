# Figure 1: ecological atlas --------
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
invalidate_figure_render_success()

# load figure data --------

fit <- read_figure_data(
  file.path(result_dir, "fitted_week_age_pathogen.csv.gz"),
  c("week_start", "age_group", "pathogen_group", "reported_pathogen_proxy", "conditional_expected_reported_cases", "typed_cases")
)
fit[, week_start := as.Date(week_start)]
weekly_inputs <- read_figure_data(
  file.path(result_dir, "weekly_input_summary.csv.gz"),
  c("week_start", "age_group", "reported_cases", "typed_cases", "vaccine_coverage_proxy_r00")
)
weekly_inputs[, week_start := as.Date(week_start)]

# panel A: total epidemic curve and typing coverage --------
# The hero panel establishes the observed surveillance burden before the
# pathogen-proxy panels.  Weekly bars retain the total report count while
# making the sparse typed subset explicit.

weekly_pathogen <- fit[, .(
  proxy = sum(reported_pathogen_proxy),
  conditional = sum(conditional_expected_reported_cases)
), by = .(week_start, pathogen_group)]
setorder(weekly_pathogen, pathogen_group, week_start)
weekly_pathogen[, proxy_smooth := frollmean(proxy, 13, align = "center", fill = NA_real_), by = pathogen_group]
weekly_total <- weekly_inputs[, .(
  reported_cases = sum(reported_cases),
  typed_cases = sum(typed_cases)
), by = week_start]

if (any(weekly_total$typed_cases < 0 | weekly_total$typed_cases > weekly_total$reported_cases)) {
  stop("Typed cases must be non-negative and cannot exceed reported cases in Panel A")
}

weekly_total[, untyped_cases := reported_cases - typed_cases]

weekly_burden <- melt(
  weekly_total,
  id.vars = "week_start",
  measure.vars = c("untyped_cases", "typed_cases"),
  variable.name = "typing_status", value.name = "cases"
)

weekly_burden[, typing_status := factor(
  typing_status,
  levels = c("untyped_cases", "typed_cases"),
  labels = c("Without", "With")
)]

typing_status_colours <- c(
  # Surveillance-status colours are reserved for Panel A.  Pathogen colours
  # (orange, teal, navy) remain exclusive to the subtype panels.
  "Without" = "#B9C0C5",
  "With" = hfmd_palette[["red"]]
)

main_year_breaks <- seq(2010, 2025, by = 2)
main_date_breaks <- as.Date(paste0(main_year_breaks, "-01-01"))
main_date_limits <- as.Date(c("2010-01-01", "2025-12-31"))
monitoring_year_breaks <- c(2010, 2015, 2020, 2025)
monitoring_date_breaks <- as.Date(paste0(monitoring_year_breaks, "-01-01"))
weekly_case_breaks <- pretty(weekly_total$reported_cases)

p1a <- ggplot(weekly_burden, aes(x = week_start, y = cases, fill = typing_status)) +
  annotate(
    "rect", xmin = as.Date("2020-01-01"), xmax = as.Date("2022-12-31"),
    ymin = -Inf, ymax = Inf, fill = hfmd_palette[["faint"]], alpha = 0.80
  ) +
  geom_col(width = 6.5, colour = NA) +
  scale_fill_manual(values = typing_status_colours) +
  scale_x_date(breaks = main_date_breaks, date_labels = "%Y", expand = c(0, 0)) +
  scale_y_continuous(labels = scales::label_comma(), expand = c(0,0), breaks = weekly_case_breaks, limits = range(weekly_case_breaks)) +
  coord_cartesian(xlim = main_date_limits) +
  labs(x = "Date", y = "Weekly reported cases", fill = "Typing status") +
  theme_hfmd_legend(position = "inside", inside = c(1, 1), justification = c(1, 1)) +
  guides(fill = guide_legend(ncol = 1, byrow = TRUE, override.aes = list(colour = NA, size = 1)))

# p1a

# panel B: pathogen-specific burden over time --------
# Retain the reconstructed subtype series as the bridge from observed reports
# in Panel A to the composition and phenology summaries below.

pathogen_case_breaks <- pretty(c(weekly_pathogen$proxy, weekly_total$reported_cases), n = 5)

p1b <- ggplot() +
  annotate(
    "rect", xmin = as.Date("2020-01-01"), xmax = as.Date("2022-12-31"),
    ymin = -Inf, ymax = Inf, fill = hfmd_palette[["light"]], alpha = 0.34
  ) +
  geom_area(
    data = weekly_pathogen[!is.na(proxy_smooth)],
    aes(x = week_start, y = proxy_smooth, fill = pathogen_group),
    position = "stack", alpha = 0.88, colour = NA
  ) +
  geom_line(
    data = weekly_total,
    aes(x = week_start, y = reported_cases),
    colour = hfmd_palette[["ink"]], linewidth = 0.22, alpha = 0.30
  ) +
  scale_fill_manual(values = pathogen_colours, labels = pathogen_labels) +
  scale_x_date(breaks = main_date_breaks, date_labels = "%Y", expand = c(0, 0)) +
  scale_y_continuous(labels = scales::label_comma(), expand = c(0, 0), breaks = pathogen_case_breaks, limits = range(pathogen_case_breaks)) +
  coord_cartesian(xlim = main_date_limits) +
  labs(x = "Date", y = "Weekly reported-case proxy", fill = "Pathogen") +
  theme_hfmd_legend(position = "inside", inside = c(1, 1), justification = c(1, 1)) +
  guides(fill = guide_legend(ncol = 1, byrow = TRUE, override.aes = list(colour = NA, size = 1)))

# p1b

# panel C: typing intensity by age and week --------
typing_effort <- weekly_inputs[, .(typed_cases = sum(typed_cases)), by = .(week_start, age_group)]
typing_effort[, age := factor(age_group, levels = rev(age_order), labels = rev(unname(age_labels[age_order])))]
overall_typed_fraction <- sum(weekly_inputs$typed_cases) / sum(weekly_inputs$reported_cases)
typing_effort_breaks <- c(0, 10, 100, 1000)
p1c <- ggplot(typing_effort, aes(x = week_start, y = age, fill = log1p(typed_cases))) +
  geom_tile(height = 0.88) +
  scale_fill_gradientn(
    colours = c("white", hfmd_palette[["cream"]], hfmd_palette[["teal"]], hfmd_palette[["navy"]]),
    breaks = log1p(typing_effort_breaks),
    limits = log1p(range(typing_effort_breaks)),
    labels = scales::label_comma()(typing_effort_breaks),
    name = "Typed cases\nper age-week",
    guide = guide_colourbar(
      direction = "vertical", barheight = grid::unit(22, "mm"),
      barwidth = grid::unit(3.2, "mm"), title.position = "top"
    )
  ) +
  scale_x_date(breaks = main_date_breaks, date_labels = "%Y", expand = c(0, 0)) +
  coord_cartesian(xlim = main_date_limits) +
  labs(x = "Date", y = "Age group (years)") +
  theme_hfmd_legend(position = "right")

# panel D: annual typing fraction --------
annual_surveillance <- weekly_inputs[, .(
  reports = sum(reported_cases), typed = sum(typed_cases)
), by = .(year = as.integer(format(week_start, "%Y")))]
annual_surveillance[, typed_fraction := typed / reports]
typed_fraction_breaks <- pretty(annual_surveillance$typed_fraction, n = 5)
p1d <- ggplot(annual_surveillance, aes(x = year, y = typed_fraction)) +
  annotate(
    "rect", xmin = 2020, xmax = 2022, ymin = -Inf, ymax = Inf,
    fill = hfmd_palette[["light"]], alpha = 0.35
  ) +
  geom_line(colour = hfmd_palette[["teal"]], linewidth = 0.62) +
  geom_point(shape = 21, fill = hfmd_palette[["teal"]], colour = "white", stroke = 0.35, size = 1.8) +
  geom_hline(yintercept = overall_typed_fraction, linetype = "22", colour = hfmd_palette[["mid"]], linewidth = 0.38) +
  scale_x_continuous(breaks = monitoring_year_breaks) +
  scale_y_continuous(
    labels = scales::label_percent(accuracy = 0.1), breaks = typed_fraction_breaks,
    limits = range(typed_fraction_breaks), expand = c(0, 0)
  ) +
  coord_cartesian(xlim = range(monitoring_year_breaks)) +
  labs(x = "Calendar year", y = "Reports typed (%)")

# panel E: vaccine proxy by age and year --------
annual_vaccine <- weekly_inputs[, .(
  coverage = mean(vaccine_coverage_proxy_r00, na.rm = TRUE)
), by = .(year = as.integer(format(week_start, "%Y")), age_group)]
annual_vaccine[, age := factor(age_group, levels = rev(age_order), labels = rev(unname(age_labels[age_order])))]
vaccine_coverage_limit <- max(annual_vaccine$coverage, na.rm = TRUE)
vaccine_coverage_breaks <- pretty(c(0, vaccine_coverage_limit), n = 4)
p1e <- ggplot(annual_vaccine, aes(x = year, y = age, fill = coverage)) +
  geom_tile(width = 0.94, height = 0.86, colour = "white", linewidth = 0.20) +
  scale_fill_gradientn(
    colours = c("white", hfmd_palette[["cream"]], hfmd_palette[["orange"]]),
    limits = range(vaccine_coverage_breaks),
    breaks = vaccine_coverage_breaks,
    labels = scales::label_percent(accuracy = 1), name = "Estimated\nvaccine\ncoverage",
    guide = guide_colourbar(
      direction = "vertical", barheight = grid::unit(22, "mm"),
      barwidth = grid::unit(3.2, "mm"), title.position = "top"
    )
  ) +
  scale_x_continuous(breaks = main_year_breaks, expand = c(0, 0)) +
  coord_cartesian(xlim = c(2010, 2026)) +
  labs(x = "Calendar year", y = "Age group (years)") +
  theme_hfmd_legend(position = "right")

# panel F: annual EV-A71 distribution --------
annual_pathogen_distribution <- weekly_pathogen[, .(
  estimated_cases = sum(proxy)
), by = .(
  year = as.integer(format(week_start, "%Y")), pathogen_group
)]
annual_pathogen_distribution[, total_estimated_cases := sum(estimated_cases), by = year]
annual_ev_a71 <- annual_pathogen_distribution[pathogen_group == "EV_A71"]
annual_ev_a71[, ev_a71_fraction := estimated_cases / total_estimated_cases]
ev_a71_fraction_breaks <- pretty(annual_ev_a71$ev_a71_fraction, n = 5)

p1f <- ggplot(annual_ev_a71, aes(x = year, y = ev_a71_fraction)) +
  annotate(
    "rect", xmin = 2020, xmax = 2022, ymin = -Inf, ymax = Inf,
    fill = hfmd_palette[["light"]], alpha = 0.35
  ) +
  geom_vline(xintercept = 2017, linetype = "22", colour = hfmd_palette[["mid"]], linewidth = 0.38) +
  geom_line(colour = hfmd_palette[["orange"]], linewidth = 0.62) +
  geom_point(shape = 21, fill = hfmd_palette[["orange"]], colour = "white", stroke = 0.35, size = 1.8) +
  scale_x_continuous(breaks = monitoring_year_breaks) +
  scale_y_continuous(
    labels = scales::label_percent(accuracy = 1), breaks = ev_a71_fraction_breaks,
    limits = range(ev_a71_fraction_breaks), expand = c(0, 0)
  ) +
  coord_cartesian(xlim = range(monitoring_year_breaks)) +
  labs(x = "Calendar year", y = "EV-A71 fraction")

# assemble figure --------
figure1_design <- "
AAAAAA
BBBBBB
CCCCDD
EEEEFF
"
figure1 <-
  p1a + p1b + p1c + p1d + p1e + p1f +
  plot_layout(design = figure1_design, heights = c(1.18, 1.06, 0.78, 0.62), guides = "keep", tag_level = "new") +
  plot_annotation(tag_levels = "a")
# save figure --------
save_figure_bundle(figure1, output_dir, "figure1_ecological_atlas", 7.2, 8.0)
write_figure_manifest(output_dir)
message("Rendered Figure 1: ", output_dir)
