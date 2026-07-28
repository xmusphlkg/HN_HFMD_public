# Figure 3: age ecology --------
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
age_levels_display <- rev(age_order)
age_labels_display <- rev(unname(age_labels[age_order]))

# Paired counterfactual data --------
cf <- read_counterfactual_figure_data(result_dir)
estimands <- read_counterfactual_estimands(result_dir)

age_release <- estimands[
  estimand == "non_ev_competitive_release_cases" & scope %in% age_order
]
age_release[, age := factor(scope, levels = age_levels_display, labels = age_labels_display)]
age_release[, age_sort := match(scope, age_order)]
age_release[, label_hjust := ifelse(estimate < 20, 0, 0.5)]
setorder(age_release, age_sort)

under6_release <- estimands[
  scope == "vaccine_eligible_ages_lt6" & estimand == "non_ev_competitive_release_cases"
]
if (nrow(under6_release) != 1L) stop("Expected one bootstrap estimand for ages below 6 years")
under6_total <- under6_release$estimate
under6_low <- under6_release$bootstrap_low
under6_high <- under6_release$bootstrap_high
all_age_release <- age_release[, sum(estimate)]
under6_fraction <- under6_total / all_age_release

# a: locate the absolute release and its conditional uncertainty --------
age_release_breaks <- pretty(c(0, age_release$bootstrap_low, age_release$bootstrap_high), n = 5)
age_release_limits <- range(age_release_breaks)
p3a <- ggplot(age_release, aes(x = estimate, y = age)) +
  geom_vline(xintercept = 0, colour = hfmd_palette[["ink"]], linewidth = 0.40) +
  geom_segment(
    aes(x = bootstrap_low, xend = bootstrap_high, yend = age),
    colour = hfmd_palette[["navy"]], linewidth = 0.78, lineend = "round"
  ) +
  geom_point(
    shape = 21, fill = hfmd_palette[["orange"]], colour = "white",
    stroke = 0.45, size = 2.75
  ) +
  geom_text(
    aes(
      label = sprintf("%.1f (%.1f–%.1f)", estimate, bootstrap_low, bootstrap_high),
      hjust = label_hjust
    ),
    nudge_y = 0.22, vjust = 0,
    family = hfmd_font_family, size = 1.95, fontface = "bold"
  ) +
  annotate(
    "segment", x = 250, xend = 250, y = 2.72, yend = 5.28,
    colour = hfmd_palette[["teal"]], linewidth = 0.72
  ) +
  annotate(
    "text", x = 246, y = 2.35,
    label = sprintf("%.1f (95%% interval %.1f–%.1f)\n%.1f%% of all ages", under6_total, under6_low, under6_high, 100 * under6_fraction),
    hjust = 1, family = hfmd_font_family, size = 2.05,
    colour = hfmd_palette[["teal"]], fontface = "bold"
  ) +
  scale_x_continuous(
    breaks = age_release_breaks, limits = age_release_limits,
    labels = scales::label_number(accuracy = 1), expand = c(0, 0)
  ) +
  labs(x = "Estimated additional non-EV-A71\nreported-case proxies, 2017–2025", y = "Age group (years)") +
  theme(plot.margin = margin(5, 34, 5, 6)) +
  coord_cartesian(clip = "off")

# Age-specific factual burden and release --------
age_counterfactual <- cf[
  scenario %in% c("factual", "no_vaccine"),
  .(expected = sum(expected_reported_cases)),
  by = .(age_group, pathogen_class = fifelse(pathogen_group == "EV_A71", "EV-A71", "Non-EV-A71"), scenario)
]
age_counterfactual <- dcast(
  age_counterfactual, age_group + pathogen_class ~ scenario, value.var = "expected"
)

non_ev_age <- age_counterfactual[pathogen_class == "Non-EV-A71", .(
  age_group,
  factual_non_ev = factual,
  release = factual - no_vaccine
)]
release_share_ci <- estimands[
  scope %in% age_order & estimand == "non_ev_competitive_release_share",
  .(
    age_group = scope, release_share = estimate,
    release_share_low = bootstrap_low, release_share_high = bootstrap_high
  )
]
release_per_10000_ci <- estimands[
  scope %in% age_order &
    estimand == "non_ev_competitive_release_per_10000_factual_non_ev_cases",
  .(
    age_group = scope, release_per_10000 = estimate,
    release_per_10000_low = bootstrap_low, release_per_10000_high = bootstrap_high
  )
]
non_ev_age <- merge(non_ev_age, release_share_ci, by = "age_group", all.x = TRUE, sort = FALSE)
non_ev_age <- merge(non_ev_age, release_per_10000_ci, by = "age_group", all.x = TRUE, sort = FALSE)
non_ev_age[, age := factor(age_group, levels = age_levels_display, labels = age_labels_display)]
non_ev_age[, burden_share := factual_non_ev / sum(factual_non_ev)]
non_ev_age[, `:=`(
  release_share_label = sprintf(
    "%.1f%% (%.1f–%.1f%%)",
    100 * release_share, 100 * release_share_low, 100 * release_share_high
  ),
  release_share_hjust = fcase(
    release_share < 0.06, 0,
    release_share > 0.55, 1,
    default = 0.5
  ),
  release_per_10000_label = sprintf(
    "%.1f (%.1f–%.1f)",
    release_per_10000, release_per_10000_low, release_per_10000_high
  ),
  release_per_10000_hjust = fcase(
    release_per_10000 < 2, 0,
    release_per_10000 > 9, 1,
    default = 0.5
  )
)]

# b: distinguish concentration from the background burden distribution --------
share_breaks <- pretty(c(
  0, non_ev_age$burden_share,
  non_ev_age$release_share_low, non_ev_age$release_share_high
), n = 5)
share_limits <- range(share_breaks)
p3b <- ggplot(non_ev_age, aes(y = age)) +
  geom_segment(
    aes(x = release_share_low, xend = release_share_high, yend = age),
    colour = hfmd_palette[["teal"]], linewidth = 0.68, lineend = "round"
  ) +
  geom_point(
    aes(x = burden_share, fill = "Factual non-EV-A71 burden"),
    shape = 21, colour = "white", size = 2.35, stroke = 0.45
  ) +
  geom_point(
    aes(x = release_share, fill = "Additional non-EV-A71 proxies"),
    shape = 21, colour = "white", size = 2.35, stroke = 0.45
  ) +
  scale_fill_manual(
    values = c("Factual non-EV-A71 burden" = hfmd_palette[["navy"]], "Additional non-EV-A71 proxies" = hfmd_palette[["teal"]]),
    name = "Age distribution",
    breaks = c("Additional non-EV-A71 proxies", "Factual non-EV-A71 burden")
  ) +
  scale_x_continuous(
    breaks = share_breaks, limits = share_limits,
    labels = scales::label_percent(accuracy = 1),
    expand = expansion(mult = c(0.025, 0))
  ) +
  labs(x = "Age-group share of all-age non-EV-A71 reported-case proxies", y = "Age group (years)") +
  theme_hfmd_legend(
    position = "inside", inside = c(1, 0.01), justification = c(1, 0),
    background_alpha = 0.88
  ) +
  guides(fill = guide_legend(
    nrow = 2, byrow = TRUE,
    override.aes = list(shape = 21, colour = "white")
  ))

# c: normalize release to each age group's own non-EV-A71 burden --------
relative_breaks <- pretty(c(
  0, non_ev_age$release_per_10000_low, non_ev_age$release_per_10000_high
), n = 5)
relative_limits <- range(relative_breaks)
p3c <- ggplot(non_ev_age, aes(x = release_per_10000, y = age)) +
  geom_segment(
    aes(x = release_per_10000_low, xend = release_per_10000_high, yend = age),
    colour = hfmd_palette[["navy"]], linewidth = 0.72, lineend = "round"
  ) +
  geom_point(
    shape = 21, fill = hfmd_palette[["teal"]], colour = "white",
    size = 2.45, stroke = 0.45
  ) +
  scale_x_continuous(
    breaks = relative_breaks, limits = relative_limits,
    labels = scales::label_number(accuracy = 1), expand = c(0, 0)
  ) +
  labs(x = "Additional non-EV-A71 proxies per 10,000\nfactual non-EV-A71 reported-case proxies", y = NULL)

# d: show every structural scenario as an age-by-scenario result matrix --------
sensitivity_age <- read_figure_data(
  file.path(result_dir, "sensitivity_estimands.csv"),
  c("sensitivity", "scope", "estimand", "estimate", "converged")
)[
  scope %in% age_order & estimand == "non_ev_competitive_release_cases" &
    converged %in% c(TRUE, "True", "TRUE", 1),
  .(scope, sensitivity, estimate)
]
sensitivity_age[, age := factor(scope, levels = age_levels_display, labels = age_labels_display)]

scenario_key <- data.table(
  sensitivity = c(
    "primary",
    "reporting_0.01", "reporting_0.10",
    "cross_duration_3.31w", "cross_duration_23.4w",
    "cross_strength_fixed_0.37", "cross_strength_fixed_0.68", "cross_strength_fixed_0.96",
    "homologous_half_life_104w", "homologous_half_life_520w",
    "generation_one_week", "generation_three_week",
    "coverage_r10", "coverage_r25", "coverage_r50",
    "vaccine_efficacy_low", "vaccine_efficacy_high",
    "population_minus_10pct", "population_plus_10pct",
    "typed_ev_underascertain_0.67", "typed_ev_overascertain_1.5"
  ),
  category = c(
    "Primary",
    rep("Reporting", 2), rep("Heterotypic\nprotection", 5),
    rep("Immunity / generation", 4), rep("Vaccine coverage", 5),
    rep("Population / typing", 4)
  ),
  scenario_label = c(
    "Main",
    "0.01", "0.10",
    "3.31 w", "23.4 w", "0.37", "0.68", "0.96",
    "Hom. 104 w", "Hom. 520 w", "Gen. 1 w", "Gen. 3 w",
    "Cov. 10%", "Cov. 25%", "Cov. 50%", "VE 0.752", "VE 0.900",
    "Pop. -10%", "Pop. +10%", "Typing 0.67", "Typing 1.50"
  )
)
scenario_key[, category := factor(
  category,
  levels = c("Primary", "Reporting", "Heterotypic\nprotection", "Immunity / generation", "Vaccine coverage", "Population / typing")
)]
scenario_key[, scenario_label := factor(scenario_label, levels = scenario_label)]

primary_age <- age_release[, .(
  scope, sensitivity = "primary", estimate
)]
sensitivity_matrix <- rbindlist(list(primary_age, sensitivity_age[, .(scope, sensitivity, estimate)]))
sensitivity_matrix <- merge(sensitivity_matrix, scenario_key, by = "sensitivity", all.x = TRUE)
sensitivity_matrix[, age := factor(scope, levels = age_levels_display, labels = age_labels_display)]

# A signed log colour coordinate preserves direction while preventing the two
# largest reporting-fraction results from flattening the remaining 98 cells.
signed_log10 <- function(x) sign(x) * log10(1 + abs(x) / 10)
sensitivity_matrix[, fill_value := signed_log10(estimate)]
inverse_signed_log10 <- function(x) sign(x) * 10 * (10^abs(x))
fill_breaks <- pretty(sensitivity_matrix$fill_value, n = 5)
fill_limits <- range(fill_breaks)
fill_break_labels <- scales::label_number(accuracy = 1, big.mark = ",")(
  inverse_signed_log10(fill_breaks)
)

p3d <- ggplot(sensitivity_matrix, aes(x = scenario_label, y = age, fill = fill_value)) +
  geom_tile(width = 0.94, height = 0.88, colour = "white", linewidth = 0.28) +
  geom_text(
    data = sensitivity_matrix[sensitivity == "primary" | estimate < 0],
    aes(label = format_direct_number(estimate, accuracy = 1)),
    family = hfmd_font_family, size = 1.45, fontface = "bold",
    colour = hfmd_palette[["ink"]]
  ) +
  facet_grid(cols = vars(category), scales = "free_x", space = "free_x") +
  scale_fill_gradient2(
    low = hfmd_palette[["red"]], mid = "white", high = hfmd_palette[["teal"]],
    midpoint = 0, limits = fill_limits,
    breaks = fill_breaks,
    labels = fill_break_labels,
    name = "Additional\nnon-EV-A71\nproxies",
    guide = guide_colourbar(
      direction = "vertical", barheight = grid::unit(25, "mm"),
      barwidth = grid::unit(3.2, "mm"), title.position = "top"
    )
  ) +
  labs(x = "Prespecified structural or measurement scenario", y = "Age group (years)") +
  theme(
    axis.line.x = element_blank(), axis.ticks.x = element_blank(),
    axis.text.x = element_text(angle = 55, hjust = 1, vjust = 1, size = 5.0),
    strip.text.x = element_text(size = hfmd_strip_text_dense_size),
    strip.clip = "off",
    panel.spacing.x = grid::unit(1.4, "mm")
  ) +
  theme_hfmd_legend(position = "right")

# e: translate the age decomposition into retained public-health benefit --------
age_balance <- dcast(
  age_counterfactual[, .(
    effect = fifelse(pathogen_class == "EV-A71", no_vaccine - factual, factual - no_vaccine)
  ), by = .(age_group, pathogen_class)],
  age_group ~ pathogen_class, value.var = "effect"
)
setnames(age_balance, c("EV-A71", "Non-EV-A71"), c("ev_averted", "non_ev_release"))
retained_ci <- estimands[
  scope %in% age_order & estimand == "retained_ev_a71_benefit_percent",
  .(
    age_group = scope, retained_percent = estimate,
    retained_low = bootstrap_low, retained_high = bootstrap_high
  )
]
net_ci <- estimands[
  scope %in% age_order & estimand == "net_all_pathogen_reported_cases_averted",
  .(
    age_group = scope, net_averted = estimate,
    net_low = bootstrap_low, net_high = bootstrap_high
  )
]
age_balance <- merge(age_balance, retained_ci, by = "age_group", all.x = TRUE, sort = FALSE)
age_balance <- merge(age_balance, net_ci, by = "age_group", all.x = TRUE, sort = FALSE)
age_balance[, age := factor(age_group, levels = age_levels_display, labels = age_labels_display)]
age_balance[, `:=`(
  retained_label = sprintf(
    "%.1f%% (%.1f–%.1f%%)", retained_percent, retained_low, retained_high
  ),
  net_label = paste0(
    format_direct_number(net_averted, accuracy = 0.1), " (",
    format_direct_number(net_low, accuracy = 0.1), "–",
    format_direct_number(net_high, accuracy = 0.1), ")"
  ),
  net_label_hjust = fcase(
    net_averted < 400, 0,
    net_averted > 3000, 1,
    default = 0.5
  )
)]
overall_retained_ci <- estimands[
  scope == "all_ages" & estimand == "retained_ev_a71_benefit_percent"
]
if (nrow(overall_retained_ci) != 1L) stop("Expected one all-age retained-benefit estimand")
overall_retained <- overall_retained_ci$estimate
retained_breaks <- pretty(c(
  overall_retained, age_balance$retained_low, age_balance$retained_high
), n = 5)
retained_limits <- range(retained_breaks)
p3e <- ggplot(age_balance, aes(x = retained_percent, y = age)) +
  geom_vline(
    xintercept = overall_retained, linetype = "22",
    colour = hfmd_palette[["navy"]], linewidth = 0.46
  ) +
  geom_segment(
    aes(x = retained_low, xend = retained_high, yend = age),
    colour = hfmd_palette[["navy"]], linewidth = 0.72, lineend = "round"
  ) +
  geom_point(
    shape = 21, fill = hfmd_palette[["orange"]], colour = "white",
    size = 2.55, stroke = 0.45
  ) +
  scale_x_continuous(
    breaks = retained_breaks, limits = retained_limits,
    labels = scales::label_percent(scale = 1, accuracy = 1), expand = c(0, 0)
  ) +
  labs(
    x = "EV-A71 benefit retained after\naccounting for additional non-EV-A71 proxies",
    y = "Age group (years)"
  )

# f: close the story with the absolute net benefit in each age group --------
net_breaks <- pretty(c(0, age_balance$net_low, age_balance$net_high), n = 5)
net_limits <- range(net_breaks)
p3f <- ggplot(age_balance, aes(x = net_averted, y = age)) +
  geom_segment(
    aes(x = net_low, xend = net_high, yend = age),
    colour = hfmd_palette[["teal"]], linewidth = 0.72, lineend = "round"
  ) +
  geom_point(
    shape = 21, fill = hfmd_palette[["navy"]], colour = "white",
    size = 2.55, stroke = 0.45
  ) +
  scale_x_continuous(
    breaks = net_breaks, limits = net_limits,
    labels = scales::label_comma(), expand = c(0, 0)
  ) +
  labs(x = "Net all-pathogen reported-case proxies averted,\n2017–2025", y = NULL)

# assemble: locate -> explain -> normalize -> stress-test -> interpret --------
figure3_design <- "
AAAAAA
BBBCCC
DDDDDD
EEEFFF
"
figure3 <- p3a + p3b + p3c + free(p3d) + p3e + p3f +
  plot_layout(
    design = figure3_design,
    heights = c(1.00, 0.84, 1.18, 0.76),
    guides = "keep", tag_level = "new"
  ) +
  plot_annotation(tag_levels = "a")

save_figure_bundle(figure3, output_dir, "figure3_age_ecology", 7.2, 7.6)
write_figure_manifest(output_dir)
message("Rendered Figure 3: ", output_dir)
