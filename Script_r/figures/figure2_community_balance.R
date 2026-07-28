# Figure 2: community balance --------
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

# Figure-wide visual grammar follows Figure 1 --------
figure2_year_breaks <- c(2017, 2019, 2021, 2023, 2025)
figure2_date_breaks <- as.Date(paste0(figure2_year_breaks, "-01-01"))
figure2_date_limits <- as.Date(c("2017-01-01", "2025-12-31"))
figure2_annual_breaks <- seq(2017, 2025, by = 2)
balance_colours <- c(
  "EV-A71 proxies averted" = hfmd_palette[["orange"]],
  "Additional non-EV-A71 proxies" = hfmd_palette[["teal"]],
  "Net proxies averted" = hfmd_palette[["navy"]]
)

# Paired observation-anchored counterfactuals --------
cf <- read_counterfactual_figure_data(result_dir)
cf[, pathogen_class := fifelse(pathogen_group == "EV_A71", "EV-A71", "Non-EV-A71")]
weekly_cf <- cf[scenario %in% c("factual", "no_vaccine"), .(
  expected = sum(expected_reported_cases)
), by = .(week_start, scenario, pathogen_class)]
weekly_cf <- dcast(weekly_cf, week_start + pathogen_class ~ scenario, value.var = "expected")
weekly_cf[, paired_difference := factual - no_vaccine]
setorder(weekly_cf, pathogen_class, week_start)
weekly_cf[, smooth_difference := frollmean(paired_difference, 13, align = "center", fill = NA_real_), by = pathogen_class]
weekly_cf[, display_class := factor(
  pathogen_class,
  levels = c("EV-A71", "Non-EV-A71"),
  labels = c("EV-A71 decrease", "Non-EV increase")
)]
p2a_y_breaks <- scales::breaks_pretty(n = 4)

# a: the decisive absolute contrast --------
p2a <- ggplot(weekly_cf[!is.na(smooth_difference)], aes(x = week_start, y = smooth_difference)) +
  annotate("rect", xmin = as.Date("2020-01-01"), xmax = as.Date("2022-12-31"),
           ymin = -Inf, ymax = Inf, fill = hfmd_palette[["faint"]], alpha = 0.80) +
  geom_hline(yintercept = 0, colour = hfmd_palette[["ink"]], linewidth = 0.42) +
  geom_area(aes(fill = pathogen_class), alpha = 0.30, colour = NA) +
  geom_line(aes(colour = pathogen_class), linewidth = 0.68, lineend = "round") +
  facet_grid(display_class ~ ., scales = "free_y") +
  scale_colour_manual(values = c("EV-A71" = hfmd_palette[["orange"]], "Non-EV-A71" = hfmd_palette[["teal"]]), guide = "none") +
  scale_fill_manual(values = c("EV-A71" = hfmd_palette[["orange"]], "Non-EV-A71" = hfmd_palette[["teal"]]), guide = "none") +
  scale_x_date(breaks = figure2_date_breaks, date_labels = "%Y", expand = c(0, 0)) +
  scale_y_continuous(
    labels = scales::label_number(accuracy = 1),
    # With free y-scales, calculate breaks from each facet's own limits.
    breaks = p2a_y_breaks,
    expand = c(0, 0)
  ) +
  coord_cartesian(xlim = figure2_date_limits) +
  labs(x = NULL, y = "Weekly reported-case-proxy difference")

# b: annual community balance --------
weekly_effect <- dcast(
  weekly_cf[, .(
    effect = fifelse(pathogen_class == "EV-A71", -paired_difference, paired_difference)
  ), by = .(week_start, pathogen_class)],
  week_start ~ pathogen_class, value.var = "effect"
)
setnames(weekly_effect, c("EV-A71", "Non-EV-A71"), c("ev_averted", "non_ev_release"))
setorder(weekly_effect, week_start)
weekly_effect[, `:=`(
  net_averted = ev_averted - non_ev_release,
  year = as.integer(format(week_start, "%Y"))
)]
annual_effect <- weekly_effect[, .(
  ev_averted = sum(ev_averted),
  non_ev_release = sum(non_ev_release),
  net_averted = sum(net_averted)
), by = year]
signed_annual <- melt(
  annual_effect, id.vars = "year",
  measure.vars = c("ev_averted", "non_ev_release"),
  variable.name = "component", value.name = "value"
)
signed_annual[component == "non_ev_release", value := -value]
signed_annual[, component := factor(
  component, levels = c("ev_averted", "non_ev_release"),
    labels = c("EV-A71 proxies averted", "Additional non-EV-A71 proxies")
)]
p2b_y_breaks <- pretty(c(signed_annual$value, annual_effect$net_averted))
p2b <- ggplot(signed_annual, aes(x = year, y = value, fill = component)) +
  annotate("rect", xmin = 2019.5, xmax = 2022.5, ymin = -Inf, ymax = Inf,
           fill = hfmd_palette[["light"]], alpha = 0.35) +
  geom_hline(yintercept = 0, colour = hfmd_palette[["ink"]], linewidth = 0.40) +
  geom_col(width = 0.68) +
  scale_fill_manual(
    values = balance_colours[c("EV-A71 proxies averted", "Additional non-EV-A71 proxies")],
    guide = "none"
  ) +
  scale_x_continuous(breaks = figure2_annual_breaks, expand = c(0, 0)) +
  scale_y_continuous(
    labels = scales::label_comma(),
    breaks = p2b_y_breaks,
    limits = range(p2b_y_breaks),
    expand = c(0, 0)
  ) +
  coord_cartesian(xlim = c(2016.55, 2025.45)) +
  labs(x = "Calendar year", y = "Annual reported-case-proxy difference")

# c: the 2017-2025 community balance on a common linear scale --------
estimands <- read_counterfactual_estimands(result_dir)
all_age <- estimands[scope == "all_ages"]
ev_row <- all_age[estimand == "ev_a71_reported_cases_averted"]
release_row <- all_age[estimand == "non_ev_competitive_release_cases"]
net_row <- all_age[estimand == "net_all_pathogen_reported_cases_averted"]
totals_by_pathogen <- cf[scenario %in% c("factual", "no_vaccine"), .(
  expected = sum(expected_reported_cases)
), by = .(scenario, pathogen_group)]
totals_by_pathogen <- dcast(totals_by_pathogen, pathogen_group ~ scenario, value.var = "expected")
cv_release <- totals_by_pathogen[pathogen_group == "CV_A16", factual - no_vaccine]
other_release <- totals_by_pathogen[pathogen_group == "other_enterovirus", factual - no_vaccine]
ledger <- data.table(
  estimand = factor(
    c("EV-A71 proxies averted", "Additional non-EV-A71 proxies", "Net proxies averted"),
    levels = c("Net proxies averted", "Additional non-EV-A71 proxies", "EV-A71 proxies averted")
  ),
  estimate = c(ev_row$estimate, -release_row$estimate, net_row$estimate),
  low = c(ev_row$bootstrap_low, -release_row$bootstrap_high, net_row$bootstrap_low),
  high = c(ev_row$bootstrap_high, -release_row$bootstrap_low, net_row$bootstrap_high)
)
ledger_breaks <- pretty(c(ledger$low, ledger$high, -500, 0), n = 5)
ledger_limits <- range(ledger_breaks)
p2c <- ggplot(ledger, aes(x = estimate, y = estimand, colour = estimand)) +
  geom_vline(xintercept = 0, colour = hfmd_palette[["ink"]], linewidth = 0.40) +
  geom_segment(aes(x = low, xend = high, yend = estimand),
               linewidth = 0.78, lineend = "round") +
  geom_point(size = 2.35) +
  scale_colour_manual(values = balance_colours, guide = "none") +
  scale_x_continuous(
    breaks = ledger_breaks, limits = ledger_limits,
    labels = function(x) scales::comma(x), expand = c(0, 0)
  ) +
  labs(x = "Total estimated reported-case-proxy difference,\n2017–2025", y = NULL) +
  theme(axis.text.y = element_text(size = hfmd_axis_text_compact_size))

# d: uncertainty in the release-to-benefit ratio --------
bootstrap <- read_figure_data(
  file.path(result_dir, "bootstrap_counterfactual_metrics.csv"),
  c("replicate", "scope", "estimand", "estimate")
)
bootstrap_ratio <- dcast(
  bootstrap[scope == "all_ages" & estimand %in% c(
    "ev_a71_reported_cases_averted", "non_ev_competitive_release_cases"
  )], replicate ~ estimand, value.var = "estimate"
)
bootstrap_ratio[, ratio_per_100 := 100 * non_ev_competitive_release_cases / ev_a71_reported_cases_averted]
ratio_point <- 100 * release_row$estimate / ev_row$estimate
ratio_interval <- quantile(bootstrap_ratio$ratio_per_100, c(0.025, 0.975), na.rm = TRUE)
p2d_y_breaks <- pretty(stats::density(bootstrap_ratio$ratio_per_100, na.rm = TRUE)$y)
p2d <- ggplot(bootstrap_ratio, aes(x = ratio_per_100)) +
  geom_density(fill = "#DCE7EF", colour = hfmd_palette[["blue"]], linewidth = 0.65, alpha = 0.90) +
  geom_rug(colour = hfmd_palette[["blue"]], alpha = 0.22, linewidth = 0.28) +
  geom_vline(xintercept = 5, linetype = "22", colour = hfmd_palette[["mid"]], linewidth = 0.42) +
  geom_vline(xintercept = 10, linetype = "13", colour = hfmd_palette[["light"]], linewidth = 0.42) +
  geom_vline(xintercept = ratio_point, colour = hfmd_palette[["red"]], linewidth = 0.78) +
  annotate("segment", x = ratio_interval[[1]], xend = ratio_interval[[2]], y = 0, yend = 0,
           colour = hfmd_palette[["navy"]], linewidth = 1.2) +
  annotate("text", x = ratio_point, y = Inf,
           label = paste0("Main estimate ", format_direct_number(ratio_point, 0.1)),
           vjust = 1.35, hjust = -0.06, family = hfmd_font_family, size = 2.0,
           colour = hfmd_palette[["red"]]) +
  scale_x_continuous(limits = c(0, 10.5), breaks = c(0, 2.5, 5, 7.5, 10)) +
  scale_y_continuous(breaks = p2d_y_breaks, limits = range(p2d_y_breaks), expand = c(0, 0)) +
  labs(x = "Additional non-EV-A71 proxies per 100 EV-A71 proxies averted", y = "Bootstrap distribution")

# e: interaction-channel knockout --------
scenario_totals <- cf[
  scenario %in% c("factual", "no_vaccine", "no_cross", "no_vaccine_no_cross"),
  .(expected = sum(expected_reported_cases)), by = .(scenario, pathogen_group)
]
scenario_totals <- dcast(scenario_totals, pathogen_group ~ scenario, value.var = "expected")
knockout <- rbindlist(list(
  scenario_totals[, .(
    pathogen_group, mechanism = "Interaction retained",
    effect = fifelse(pathogen_group == "EV_A71", no_vaccine - factual, factual - no_vaccine)
  )],
  scenario_totals[, .(
    pathogen_group, mechanism = "Interaction removed",
    effect = fifelse(pathogen_group == "EV_A71", no_vaccine_no_cross - no_cross, no_cross - no_vaccine_no_cross)
  )]
))
knockout[, estimand := factor(
  pathogen_group,
  levels = c("other_enterovirus", "CV_A16", "EV_A71"),
    labels = c("Additional other-enterovirus proxies", "Additional CV-A16 proxies", "EV-A71 proxies averted")
)]
knockout_wide <- dcast(knockout, estimand ~ mechanism, value.var = "effect")
knockout_breaks <- pretty(c(0, knockout$effect), n = 5)
knockout_limits <- range(knockout_breaks) + c(-1000, 1000)
p2e <- ggplot(knockout, aes(x = effect, y = estimand)) +
  geom_segment(
    data = knockout_wide,
    aes(x = `Interaction removed`, xend = `Interaction retained`, y = estimand, yend = estimand),
    inherit.aes = FALSE, colour = hfmd_palette[["light"]], linewidth = 0.72
  ) +
  geom_point(aes(colour = mechanism, shape = mechanism), size = 2.25, stroke = 0.72) +
  geom_text(
    data = knockout[mechanism == "Interaction retained"],
    aes(label = format_direct_number(effect, accuracy = 0.1), colour = mechanism),
    nudge_x = -200, nudge_y = -0.12, hjust = 1,
    family = hfmd_font_family, size = 1.70,
    show.legend = FALSE
  ) +
  geom_text(
    data = knockout[mechanism == "Interaction removed"],
    aes(label = format_direct_number(effect, accuracy = 0.1), colour = mechanism),
    nudge_x = 200, nudge_y = 0.12, hjust = 0,
    family = hfmd_font_family, size = 1.70,
    show.legend = FALSE
  ) +
  scale_colour_manual(
    values = c("Interaction retained" = hfmd_palette[["orange"]], "Interaction removed" = hfmd_palette[["navy"]]),
    labels = c("Interaction removed" = "Without", "Interaction retained" = "With")
  ) +
  scale_shape_manual(
    values = c("Interaction retained" = 16, "Interaction removed" = 1),
    labels = c("Interaction removed" = "Without", "Interaction retained" = "With")
  ) +
  scale_x_continuous(
    breaks = knockout_breaks, limits = knockout_limits,
    labels = scales::label_comma(), expand = c(0, 0)
  ) +
  labs(x = "Total estimated reported-case-proxy difference,\n2017–2025", y = NULL,
       colour = "Heterotypic protection", shape = "Heterotypic protection") +
  theme(
    axis.text.y = element_text(size = hfmd_axis_text_compact_size),
    legend.direction = "horizontal",
    legend.title.position = 'top'
  ) +
  theme_hfmd_legend(
    position = "inside", inside = c(1, 0.01), justification = c(1, 0),
    background_alpha = 1
  ) +
  guides(
    colour = guide_legend(nrow = 1, byrow = TRUE),
    shape = guide_legend(nrow = 1, byrow = TRUE)
  )

# assemble: decision -> balance -> ledger -> uncertainty -> mechanism --------
figure2_design <- "
AAAAAA
BBBCCC
DDDEEE
"
figure2 <- p2a + p2b + p2c + p2d + p2e +
  plot_layout(design = figure2_design, heights = c(1.20, 0.88, 0.92), guides = "keep", tag_level = "new") +
  plot_annotation(tag_levels = "a")

save_figure_bundle(figure2, output_dir, "figure2_community_balance", 7.2, 6.6)
write_figure_manifest(output_dir)
message("Rendered Figure 2: ", output_dir)
