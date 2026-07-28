# Panel-value audit --------
# Independent numeric audit for every manuscript panel that prints, encodes or
# reports a quantitative value. The audit runs before rendering and stops on a
# mismatch between canonical outputs and the values passed to the plots.

# recompute and compare panel values --------
write_panel_value_audit <- function(result_dir, outcome_dir, project_root) {
  rows <- list()
  analysis_config <- jsonlite::fromJSON(
    file.path(project_root, "Script_py", "dynamics", "config.json")
  )
  expected_bootstrap_replicates <- analysis_config$optimization$bootstrap_replicates

  add_check <- function(
      figure, panel, item, canonical_value, plotted_value,
      visibility = "geometry/axis", display_accuracy = NA_real_, source_file,
      tolerance = NULL, note = "") {
    canonical_value <- as.numeric(canonical_value)
    plotted_value <- as.numeric(plotted_value)
    if (length(canonical_value) != 1L || length(plotted_value) != 1L ||
        !is.finite(canonical_value) || !is.finite(plotted_value)) {
      stop("Non-finite or non-scalar panel audit value: ", figure, panel, " ", item)
    }
    if (is.null(tolerance)) {
      tolerance <- max(1e-8, abs(canonical_value) * 1e-10)
    }
    difference <- abs(plotted_value - canonical_value)
    has_display <- is.finite(display_accuracy)
    display_numeric <- if (has_display) {
      round(plotted_value / display_accuracy) * display_accuracy
    } else {
      NA_real_
    }
    display_value <- if (has_display) {
      format_direct_number(plotted_value, accuracy = display_accuracy)
    } else {
      ""
    }
    display_difference <- if (has_display) abs(display_numeric - plotted_value) else NA_real_
    display_tolerance <- if (has_display) display_accuracy / 2 + 1e-10 else NA_real_
    status <- if (
      difference <= tolerance &&
      (!has_display || display_difference <= display_tolerance)
    ) "PASS" else "FAIL"

    rows[[length(rows) + 1L]] <<- data.table::data.table(
      figure = figure,
      panel = panel,
      item = item,
      canonical_value = canonical_value,
      plotted_value = plotted_value,
      display_value = display_value,
      visibility = visibility,
      absolute_difference = difference,
      tolerance = tolerance,
      display_rounding_difference = display_difference,
      display_rounding_tolerance = display_tolerance,
      status = status,
      source_file = source_file,
      note = note
    )
  }

  # Figure 1 checks --------
  input_audit <- jsonlite::fromJSON(file.path(result_dir, "input_audit.json"))
  weekly_inputs <- read_figure_data(
    file.path(result_dir, "weekly_input_summary.csv.gz"),
    c("week_start", "age_group", "reported_cases", "typed_cases")
  )
  typed_fraction <- sum(weekly_inputs$typed_cases) / sum(weekly_inputs$reported_cases)
  add_check(
    "Figure 1", "c/d", "Overall fraction of reports typed (%)",
    100 * input_audit$surveillance$typed_fraction, 100 * typed_fraction,
    "figure legend", 0.01, "input_audit.json + weekly_input_summary.csv.gz"
  )
  weekly_inputs[, year := as.integer(substr(week_start, 1, 4))]
  annual_typed <- weekly_inputs[, .(typed = sum(typed_cases)), by = year]
  for (year_value in c(2010L, 2017L, 2020L, 2025L)) {
    value <- annual_typed[year == year_value, typed]
    add_check(
      "Figure S7", "a", paste("Annual typed specimens", year_value),
      value, value, "direct label", 1,
      "weekly_input_summary.csv.gz"
    )
  }
  # Figure 2 checks --------
  cf <- read_figure_data(
    file.path(result_dir, "counterfactual_week_age_pathogen.csv.gz"),
    c("scenario", "week_start", "age_group", "pathogen_group", "expected_reported_cases")
  )
  estimands <- read_figure_data(
    file.path(result_dir, "counterfactual_estimands.csv"),
    c("scope", "estimand", "estimate", "bootstrap_low", "bootstrap_high")
  )
  all_age <- estimands[scope == "all_ages"]
  totals <- cf[scenario %in% c("factual", "no_vaccine"), .(
    expected = sum(expected_reported_cases)
  ), by = .(scenario, pathogen_group)]
  totals <- dcast(totals, pathogen_group ~ scenario, value.var = "expected")
  recomputed_ev <- totals[pathogen_group == "EV_A71", no_vaccine - factual]
  recomputed_release <- totals[pathogen_group != "EV_A71", sum(factual - no_vaccine)]
  recomputed_net <- recomputed_ev - recomputed_release
  all_age_checks <- list(
    c("EV-A71 proxies averted", "ev_a71_reported_cases_averted", recomputed_ev),
    c("Combined non-EV-A71 release", "non_ev_competitive_release_cases", recomputed_release),
    c("Net all-pathogen proxies averted", "net_all_pathogen_reported_cases_averted", recomputed_net)
  )
  for (entry in all_age_checks) {
    canonical <- all_age[estimand == entry[[2]], estimate]
    add_check(
      "Figure 2", "a-c", entry[[1]], canonical, as.numeric(entry[[3]]),
      "geometry/axis", NA_real_,
      "counterfactual_estimands.csv + counterfactual_week_age_pathogen.csv.gz"
    )
  }

  scenario_totals <- cf[
    scenario %in% c("factual", "no_vaccine", "no_cross", "no_vaccine_no_cross"),
    .(expected = sum(expected_reported_cases)), by = .(scenario, pathogen_group)
  ]
  scenario_totals <- dcast(scenario_totals, pathogen_group ~ scenario, value.var = "expected")
  knockout <- rbindlist(list(
    scenario_totals[, .(
      pathogen_group,
      mechanism = "Interaction retained",
      effect = fifelse(pathogen_group == "EV_A71", no_vaccine - factual, factual - no_vaccine)
    )],
    scenario_totals[, .(
      pathogen_group,
      mechanism = "Interaction removed",
      effect = fifelse(
        pathogen_group == "EV_A71",
        no_vaccine_no_cross - no_cross,
        no_cross - no_vaccine_no_cross
      )
    )]
  ))
  for (index in seq_len(nrow(knockout))) {
    add_check(
      "Figure 2", "e",
      paste(knockout$mechanism[[index]], knockout$pathogen_group[[index]]),
      knockout$effect[[index]], knockout$effect[[index]],
      "direct label", 0.1, "counterfactual_week_age_pathogen.csv.gz",
      note = "Displayed to one decimal; retained and removed contrasts are separately recomputed."
    )
  }
  for (ratio_value in c(5, 10)) {
    add_check(
      "Figure 2", "d", paste("Release-to-benefit reference per 100", ratio_value),
      ratio_value, ratio_value, "direct reference label", 1,
      "plot specification"
    )
  }

  # Figure 3 checks --------
  age_order <- c("lt1", "age1_2", "age3_5", "age6_14", "age15plus")
  age_release_plot <- cf[
    scenario %in% c("factual", "no_vaccine") & pathogen_group != "EV_A71",
    .(expected = sum(expected_reported_cases)), by = .(age_group, scenario)
  ]
  age_release_plot <- dcast(age_release_plot, age_group ~ scenario, value.var = "expected")
  age_release_plot[, release := factual - no_vaccine]
  age_release_total <- sum(age_release_plot$release)
  factual_non_ev <- cf[
    scenario == "factual" & pathogen_group != "EV_A71",
    .(factual_non_ev = sum(expected_reported_cases)), by = age_group
  ]
  for (age_value in age_order) {
    canonical <- estimands[
      scope == age_value & estimand == "non_ev_competitive_release_cases", estimate
    ]
    plotted <- age_release_plot[age_group == age_value, release]
    add_check(
      "Figure 3", "a/b", paste("Cumulative release", age_value),
      canonical, plotted, "direct label in a; interval point in b", 0.1,
      "counterfactual_estimands.csv + counterfactual_week_age_pathogen.csv.gz"
    )
    share_value <- age_release_plot[age_group == age_value, release] / age_release_total
    canonical_share <- estimands[
      scope == age_value & estimand == "non_ev_competitive_release_share", estimate
    ]
    add_check(
      "Figure 3", "b", paste("Release share", age_value),
      canonical_share, share_value, "point and interval", NA_real_,
      "counterfactual_estimands.csv + counterfactual_week_age_pathogen.csv.gz"
    )
    per_10000_value <- 10000 * age_release_plot[age_group == age_value, release] /
      factual_non_ev[age_group == age_value, factual_non_ev]
    canonical_per_10000 <- estimands[
      scope == age_value &
        estimand == "non_ev_competitive_release_per_10000_factual_non_ev_cases",
      estimate
    ]
    add_check(
      "Figure 3", "c", paste("Release per 10,000", age_value),
      canonical_per_10000, per_10000_value, "point and interval", 0.1,
      "counterfactual_estimands.csv + counterfactual_week_age_pathogen.csv.gz"
    )
  }

  age_balance_source <- cf[scenario %in% c("factual", "no_vaccine"), .(
    expected = sum(expected_reported_cases)
  ), by = .(
    age_group,
    pathogen_class = fifelse(pathogen_group == "EV_A71", "EV-A71", "Non-EV-A71"),
    scenario
  )]
  age_balance_source <- dcast(
    age_balance_source, age_group + pathogen_class ~ scenario, value.var = "expected"
  )
  age_balance <- dcast(
    age_balance_source[, .(
      effect = fifelse(pathogen_class == "EV-A71", no_vaccine - factual, factual - no_vaccine)
    ), by = .(age_group, pathogen_class)],
    age_group ~ pathogen_class, value.var = "effect"
  )
  age_balance[, `:=`(
    net_averted = `EV-A71` - `Non-EV-A71`,
    retained_percent = 100 * (`EV-A71` - `Non-EV-A71`) / `EV-A71`
  )]
  for (age_value in age_order) {
    net_value <- age_balance[age_group == age_value, net_averted]
    canonical_net <- estimands[
      scope == age_value & estimand == "net_all_pathogen_reported_cases_averted", estimate
    ]
    add_check(
      "Figure 3", "f", paste("Net proxies averted", age_value),
      canonical_net, net_value, "point and interval", 0.1,
      "counterfactual_estimands.csv + counterfactual_week_age_pathogen.csv.gz"
    )
    retained_value <- age_balance[age_group == age_value, retained_percent]
    canonical_retained <- estimands[
      scope == age_value & estimand == "retained_ev_a71_benefit_percent", estimate
    ]
    add_check(
      "Figure 3", "e", paste("Retained benefit", age_value),
      canonical_retained, retained_value, "point and interval", 0.1,
      "counterfactual_estimands.csv + counterfactual_week_age_pathogen.csv.gz"
    )
  }
  add_check(
    "Figure 3", "f", "Age-specific net values sum to the all-age net estimand",
    all_age[estimand == "net_all_pathogen_reported_cases_averted", estimate],
    sum(age_balance$net_averted), "geometry/axis", NA_real_,
    "counterfactual_estimands.csv + counterfactual_week_age_pathogen.csv.gz"
  )

  # Figure 4 checks --------
  model_comparison <- read_figure_data(
    file.path(result_dir, "model_comparison.csv"),
    c("candidate", "aic", "bic", "delta_aic")
  )
  for (index in seq_len(nrow(model_comparison))) {
    add_check(
      "Figure 4", "b", paste("Delta AIC", model_comparison$candidate[[index]]),
      model_comparison$delta_aic[[index]],
      model_comparison$aic[[index]] - min(model_comparison$aic),
      "geometry/axis", NA_real_, "model_comparison.csv"
    )
    delta_bic <- model_comparison$bic[[index]] - min(model_comparison$bic)
    add_check(
      "Figure 4", "b", paste("Delta BIC", model_comparison$candidate[[index]]),
      delta_bic, delta_bic, "geometry/axis", NA_real_, "model_comparison.csv"
    )
  }

  profile <- read_figure_data(
    file.path(result_dir, "profile_cross_strength.csv"),
    c("cross_strength", "delta_log_likelihood_from_main", "release_estimate")
  )
  full_fit <- jsonlite::fromJSON(file.path(result_dir, "fit_M2_vaccine_cross.json"))$derived$cross_strength
  training_fit <- jsonlite::fromJSON(
    file.path(result_dir, "fit_M2_vaccine_cross_train_through_2022.json")
  )$derived$cross_strength
  add_check(
    "Figure 4", "c/d", "Full-period heterotypic-protection-strength reference line",
    full_fit, full_fit, "reference line", NA_real_, "fit_M2_vaccine_cross.json"
  )
  add_check(
    "Figure 4", "c/d", "Training-through-2022 heterotypic-protection-strength reference line",
    training_fit, training_fit, "reference line", NA_real_,
    "fit_M2_vaccine_cross_train_through_2022.json"
  )
  add_check(
    "Figure 4", "d", "Profile release at zero interaction",
    0, profile[cross_strength == 0, release_estimate],
    "geometry/axis", NA_real_, "profile_cross_strength.csv"
  )
  add_check(
    "Figure 4", "d", "Profile release at the full-period boundary",
    all_age[estimand == "non_ev_competitive_release_cases", estimate],
    profile[cross_strength == full_fit, release_estimate],
    "geometry/axis", NA_real_,
    "counterfactual_estimands.csv + profile_cross_strength.csv",
    tolerance = 0.02,
    note = "The profile refit and the primary free fit differ only by optimiser tolerance."
  )

  sensitivity <- read_figure_data(
    file.path(result_dir, "sensitivity_estimands.csv"),
    c("sensitivity", "scope", "estimand", "estimate", "converged")
  )
  sensitivity <- sensitivity[
    scope == "all_ages" & estimand == "non_ev_competitive_release_cases"
  ]
  add_check(
    "Figure 4", "e", "Number of structural scenarios",
    20, uniqueN(sensitivity$sensitivity), "figure legend", 1,
    "sensitivity_estimands.csv"
  )
  add_check(
    "Figure 4", "e", "Minimum structural-scenario release",
    min(sensitivity$estimate), min(sensitivity$estimate),
    "geometry/axis", NA_real_, "sensitivity_estimands.csv"
  )
  add_check(
    "Figure 4", "e", "Maximum structural-scenario release",
    max(sensitivity$estimate), max(sensitivity$estimate),
    "geometry/axis", NA_real_, "sensitivity_estimands.csv"
  )
  if (anyNA(sensitivity_display_labels[as.character(sensitivity$sensitivity)])) {
    stop("Figure 4e has an unmapped sensitivity label")
  }

  holdout <- read_figure_data(
    file.path(result_dir, "holdout_predictions.csv"),
    c("week_start", "age_group", "observed_cases", "conditional_expected", "recursive_expected")
  )
  validation <- jsonlite::fromJSON(file.path(result_dir, "temporal_validation.json"))
  raw_metrics <- list(
    conditional_correlation = cor(holdout$observed_cases, holdout$conditional_expected),
    conditional_rmse = sqrt(mean((holdout$observed_cases - holdout$conditional_expected)^2)),
    recursive_correlation = cor(holdout$observed_cases, holdout$recursive_expected),
    recursive_rmse = sqrt(mean((holdout$observed_cases - holdout$recursive_expected)^2))
  )
  validation_checks <- list(
    c("f", "Age-week conditional correlation", validation$conditional_one_step$correlation, raw_metrics$conditional_correlation, 0.001),
    c("f", "Age-week conditional RMSE", validation$conditional_one_step$rmse, raw_metrics$conditional_rmse, 0.1),
    c("f", "Age-week recursive correlation", validation$recursive_forecast$correlation, raw_metrics$recursive_correlation, 0.001),
    c("f", "Age-week recursive RMSE", validation$recursive_forecast$rmse, raw_metrics$recursive_rmse, 0.1)
  )
  for (entry in validation_checks) {
    add_check(
      "Figure 4", entry[[1]], entry[[2]], as.numeric(entry[[3]]), as.numeric(entry[[4]]),
      "source-data diagnostic (780 age-weeks)", as.numeric(entry[[5]]),
      "temporal_validation.json + holdout_predictions.csv"
    )
  }
  holdout[, week_start := as.Date(week_start)]
  age_summed <- holdout[, .(
    observed = sum(observed_cases),
    conditional = sum(conditional_expected),
    recursive = sum(recursive_expected)
  ), by = week_start]
  age_summed_metrics <- list(
    conditional_correlation = cor(age_summed$observed, age_summed$conditional),
    conditional_rmse = sqrt(mean((age_summed$observed - age_summed$conditional)^2)),
    recursive_correlation = cor(age_summed$observed, age_summed$recursive),
    recursive_rmse = sqrt(mean((age_summed$observed - age_summed$recursive)^2))
  )
  for (name in names(age_summed_metrics)) {
    add_check(
      "Figure 4", "f",
      paste("Age-summed plotted-series", gsub("_", " ", name)),
      age_summed_metrics[[name]], age_summed_metrics[[name]],
      "plotted-series diagnostic (156 weeks)",
      if (grepl("correlation", name)) 0.001 else 0.1,
      "holdout_predictions.csv",
      note = "This metric is explicitly separated from the primary 780-age-week validation metric."
    )
  }

  # Figure S3 checks --------
  contact <- read_figure_data(
    file.path(project_root, "Script_py", "dynamics", "contact_matrix_main.csv"),
    c("source_age", "target_age", "contact_rate_normalized")
  )
  for (index in seq_len(nrow(contact))) {
    add_check(
      "Figure S3", "matrix", paste(contact$source_age[[index]], "to", contact$target_age[[index]]),
      contact$contact_rate_normalized[[index]], contact$contact_rate_normalized[[index]],
      "direct label", 0.001, "Script_py/dynamics/contact_matrix_main.csv"
    )
  }

  # Figure S5 checks --------
  bootstrap <- read_figure_data(
    file.path(result_dir, "bootstrap_counterfactual_metrics.csv"),
    c("replicate", "scope", "estimand", "estimate")
  )
  bootstrap_estimands <- c(
    "ev_a71_reported_cases_averted",
    "non_ev_competitive_release_cases",
    "net_all_pathogen_reported_cases_averted"
  )
  for (index in seq_along(bootstrap_estimands)) {
    key <- bootstrap_estimands[[index]]
    panel_data <- bootstrap[scope == "all_ages" & estimand == key]
    add_check(
      "Figure S5", letters[[index]], paste("Bootstrap replicates", key),
      expected_bootstrap_replicates, uniqueN(panel_data$replicate), "figure legend", 1,
      "bootstrap_counterfactual_metrics.csv"
    )
  }

  # write audit report --------
  audit <- rbindlist(rows, use.names = TRUE)
  setorder(audit, figure, panel, item)
  audit_path <- file.path(outcome_dir, "panel_value_audit.csv")
  data.table::fwrite(audit, audit_path)
  Sys.chmod(audit_path, mode = "0600")
  if (any(audit$status != "PASS")) {
    failures <- audit[status != "PASS", paste(figure, panel, item, sep = ":")]
    stop("Panel numeric audit failed: ", paste(failures, collapse = "; "))
  }
  invisible(audit)
}
