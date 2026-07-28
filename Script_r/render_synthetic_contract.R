#!/usr/bin/env Rscript

# Render the complete visual contract from fully synthetic validation summaries.
# This entry point never reads AnalysisOutput/ or Outcome/ and never represents
# the lightweight validation baseline as a fitted scientific result.

options(stringsAsFactors = FALSE, warn = 1)
Sys.umask("0077")

synthetic_render_root <- function(path, run_id) {
  root <- normalizePath(path, mustWork = TRUE)
  components <- strsplit(root, .Platform$file.sep, fixed = TRUE)[[1L]]
  if (!run_id %in% components) stop("Synthetic render root is not scoped beneath HFMD_RUN_ID")
  if (any(components %in% c("AnalysisOutput", "Outcome"))) {
    stop("Synthetic rendering refuses legacy AnalysisOutput/Outcome paths")
  }
  root
}

synthetic_output_dir <- function(path, run_root) {
  candidate <- normalizePath(path, mustWork = FALSE)
  if (!startsWith(candidate, paste0(run_root, .Platform$file.sep))) {
    stop("Synthetic figure output must remain inside the run staging root")
  }
  dir.create(candidate, recursive = TRUE, showWarnings = FALSE, mode = "0700")
  resolved <- normalizePath(candidate, mustWork = TRUE)
  if (!startsWith(resolved, paste0(run_root, .Platform$file.sep))) {
    stop("Synthetic figure output must remain inside the run staging root")
  }
  existing <- list.files(resolved, pattern = "^[Ff]igure.*[.](pdf|svg|png|tiff)$")
  if (length(existing)) stop("Synthetic renderer refuses to replace existing figure outputs")
  resolved
}

require_synthetic_table <- function(path, columns, run_id) {
  if (!file.exists(path)) stop("Required synthetic analysis contract is missing: ", path)
  value <- data.table::fread(path, na.strings = c("", "NA"))
  missing <- setdiff(columns, names(value))
  if (length(missing)) stop("Synthetic contract ", basename(path), " lacks: ", paste(missing, collapse = ", "))
  observed <- unique(as.character(value$run_id))
  if (length(observed) != 1L || observed[[1L]] != run_id) stop("Synthetic contract run_id mismatch: ", path)
  if ("validation_scope" %in% names(value) &&
      !all(value$validation_scope == "synthetic_validation")) {
    stop("Synthetic renderer received a non-validation analysis row: ", path)
  }
  value
}

mark_synthetic_validation <- function(plot, detail) {
  plot + plot_annotation(
    title = "SYNTHETIC VALIDATION — NOT FOR SCIENTIFIC INFERENCE",
    subtitle = detail,
    theme = theme(
      plot.title = element_text(
        family = hfmd_font_family, face = "bold", size = 9,
        colour = hfmd_palette[["red"]], hjust = 0
      ),
      plot.subtitle = element_text(
        family = hfmd_font_family, size = 6.2,
        colour = hfmd_palette[["mid"]], hjust = 0
      ),
      plot.margin = margin(5, 6, 5, 6)
    )
  )
}

save_synthetic <- function(plot, output_dir, name, detail) {
  marked <- mark_synthetic_validation(plot, detail)
  save_figure_bundle(marked, output_dir, name)
}

render_synthetic_contract <- function(root, run_root, main_dir, supplementary_dir) {
  root <- normalizePath(root, mustWork = TRUE)
  .libPaths(c(file.path(root, ".r_library"), .libPaths()))
  source(file.path(root, "Script_r", "common.R"), local = FALSE)
  run_id <- require_hfmd_run_id(always = TRUE)
  profile <- tolower(Sys.getenv("HFMD_PROFILE", unset = ""))
  if (!profile %in% c("ci", "synthetic")) {
    stop("render_synthetic_contract.R is restricted to ci or synthetic profiles")
  }
  run_root <- synthetic_render_root(run_root, run_id)
  main_dir <- synthetic_output_dir(main_dir, run_root)
  supplementary_dir <- synthetic_output_dir(supplementary_dir, run_root)
  visual_contract_path <- visual_contract_for_render(root)
  old_options <- options(
    hfmd.project_root = root,
    hfmd.visual_contract = visual_contract_path,
    hfmd.png_dpi = as.integer(Sys.getenv("HFMD_SYNTHETIC_PNG_DPI", unset = "120")),
    hfmd.tiff_dpi = as.integer(Sys.getenv("HFMD_SYNTHETIC_TIFF_DPI", unset = "150"))
  )
  on.exit(options(old_options), add = TRUE)
  render_visual_contract <- read_hfmd_visual_contract(visual_contract_path)

  ecological_path <- file.path(run_root, "analysis", "ecological", "annual_validation_metrics.csv")
  pathogen_path <- file.path(run_root, "analysis", "dynamics", "annual_pathogen_validation.csv")
  typing_path <- file.path(run_root, "analysis", "dynamics", "typing_selection_validation.csv")
  rolling_path <- file.path(run_root, "analysis", "dynamics", "rolling_origin_validation.csv")

  ecological <- require_synthetic_table(
    ecological_path,
    c(
      "run_id", "validation_scope", "synthetic_region", "year", "reported_cases",
      "typed_cases", "typing_resolution_fraction", "under_six_case_fraction",
      "population", "cases_per_100000", "mean_vaccine_proxy", "weeks_observed"
    ),
    run_id
  )
  pathogen <- require_synthetic_table(
    pathogen_path,
    c(
      "run_id", "validation_scope", "year", "pathogen_group", "reported_cases",
      "typed_cases", "reported_case_fraction", "typed_case_fraction", "mean_vaccine_proxy"
    ),
    run_id
  )
  typing <- require_synthetic_table(
    typing_path,
    c(
      "run_id", "validation_scope", "synthetic_region", "year", "resolved_pathogen_cases",
      "not_tested_cases", "typing_eligible_cases", "resolved_pathogen_fraction"
    ),
    run_id
  )
  rolling <- require_synthetic_table(
    rolling_path,
    c(
      "run_id", "validation_scope", "validation_model", "test_year",
      "observed_total_cases", "predicted_total_cases", "total_case_log_score",
      "typing_log_score", "joint_log_score"
    ),
    run_id
  )

  ecological[, year := as.integer(year)]
  pathogen[, year := as.integer(year)]
  typing[, year := as.integer(year)]
  rolling[, test_year := as.integer(test_year)]
  annual <- ecological[, .(
    reported_cases = sum(reported_cases),
    typed_cases = sum(typed_cases),
    population = sum(population),
    mean_vaccine_proxy = weighted.mean(mean_vaccine_proxy, pmax(population, 1)),
    under_six_case_fraction = weighted.mean(under_six_case_fraction, pmax(reported_cases, 1)),
    cases_per_100000 = 1e5 * sum(reported_cases) / sum(population)
  ), by = year]

  synthetic_pathogen_colours <- c(
    ev_a71 = hfmd_palette[["orange"]],
    cv_a16 = hfmd_palette[["teal"]],
    other_enterovirus = hfmd_palette[["navy"]]
  )
  synthetic_pathogen_labels <- c(
    ev_a71 = "EV-A71", cv_a16 = "CV-A16",
    other_enterovirus = "Other enteroviruses"
  )
  pathogen[, pathogen_group := factor(
    pathogen_group,
    levels = names(synthetic_pathogen_colours)
  )]
  if (anyNA(pathogen$pathogen_group)) stop("Synthetic pathogen contract contains an unregistered pathogen_group")
  synthetic_regions <- sort(unique(as.character(ecological$synthetic_region)))
  synthetic_region_colours <- setNames(
    rep(
      unname(hfmd_palette[c("navy", "teal", "orange", "blue")]),
      length.out = length(synthetic_regions)
    ),
    synthetic_regions
  )
  synthetic_region_scale <- function() {
    scale_colour_manual(
      values = synthetic_region_colours,
      breaks = synthetic_regions,
      name = "Fictional region"
    )
  }

  # Main Figure 1: longitudinal validation atlas --------
  f1a <- ggplot(annual, aes(year, reported_cases)) +
    geom_col(fill = hfmd_palette[["ink"]], width = 0.78) +
    geom_line(aes(y = typed_cases), colour = hfmd_palette[["cream"]], linewidth = 0.8) +
    labs(x = NULL, y = "Synthetic reported cases")
  f1b <- ggplot(pathogen, aes(year, reported_case_fraction, fill = pathogen_group)) +
    geom_area(position = "stack", alpha = 0.95) +
    scale_fill_manual(values = synthetic_pathogen_colours, labels = synthetic_pathogen_labels, name = "Synthetic pathogen group") +
    labs(x = NULL, y = "Synthetic fraction")
  f1c <- ggplot(annual, aes(year, mean_vaccine_proxy)) +
    geom_line(colour = hfmd_palette[["orange"]], linewidth = 0.75) +
    geom_point(colour = hfmd_palette[["orange"]], size = 1.3) +
    labs(x = "Year", y = "Synthetic vaccine proxy")
  figure1 <- add_panel_tag(f1a, "a") / add_panel_tag(f1b, "b") / add_panel_tag(f1c, "c") +
    plot_layout(heights = c(1.45, 1, 0.8), guides = "collect")
  save_synthetic(figure1, main_dir, "figure1_ecological_atlas", "Contract plumbing only; no formal surveillance reconstruction or model fit was executed.")

  # Main Figure 2: synthetic region/year association display --------
  f2a <- ggplot(ecological, aes(mean_vaccine_proxy, cases_per_100000, colour = synthetic_region)) +
    geom_point(size = 1.5, alpha = 0.8) +
    geom_path(aes(group = synthetic_region), linewidth = 0.45, alpha = 0.6) +
    synthetic_region_scale() +
    labs(x = "Synthetic vaccine proxy", y = "Cases per 100,000", colour = "Fictional region")
  f2b <- ggplot(ecological, aes(year, cases_per_100000, colour = synthetic_region)) +
    geom_line(linewidth = 0.6) + geom_point(size = 1.1) +
    synthetic_region_scale() +
    labs(x = "Year", y = "Synthetic rate", colour = "Fictional region")
  f2c <- ggplot(ecological, aes(year, typing_resolution_fraction, colour = synthetic_region)) +
    geom_line(linewidth = 0.6) + geom_point(size = 1.1) +
    synthetic_region_scale() +
    labs(x = "Year", y = "Typing resolution", colour = "Fictional region")
  figure2 <- add_panel_tag(f2a, "a") / (add_panel_tag(f2b, "b") | add_panel_tag(f2c, "c")) +
    plot_layout(heights = c(1.35, 1), guides = "collect")
  save_synthetic(figure2, main_dir, "figure2_county_ecological_effects", "Fictional-region summaries validate layout and contracts; they are not ecological effect estimates.")

  # Main Figure 3: observed synthetic community composition, never a counterfactual --------
  f3a <- ggplot(pathogen, aes(year, reported_cases, fill = pathogen_group)) +
    geom_col(position = "stack") +
    scale_fill_manual(values = synthetic_pathogen_colours, labels = synthetic_pathogen_labels, name = "Synthetic pathogen group") +
    labs(x = "Year", y = "Synthetic reported cases")
  f3b <- ggplot(pathogen, aes(year, typed_case_fraction, colour = pathogen_group)) +
    geom_line(linewidth = 0.65) + geom_point(size = 1.1) +
    scale_colour_manual(values = synthetic_pathogen_colours, labels = synthetic_pathogen_labels, name = "Synthetic pathogen group") +
    labs(x = "Year", y = "Typed-case fraction")
  figure3 <- add_panel_tag(f3a, "a") / add_panel_tag(f3b, "b") + plot_layout(heights = c(1.35, 1), guides = "collect")
  save_synthetic(figure3, main_dir, "figure3_community_balance", "No vaccination counterfactual, release estimand, or community-balance claim was computed.")

  # Main Figure 4: age-share contract proxy --------
  f4a <- ggplot(ecological, aes(year, under_six_case_fraction, colour = synthetic_region)) +
    geom_line(linewidth = 0.65) + geom_point(size = 1.15) +
    synthetic_region_scale() +
    labs(x = "Year", y = "Synthetic under-six case fraction", colour = "Fictional region")
  f4b <- ggplot(ecological, aes(cases_per_100000, under_six_case_fraction, size = population, colour = mean_vaccine_proxy)) +
    geom_point(alpha = 0.75) +
    scale_colour_gradientn(colours = hfmd_sequential_colours, name = "Synthetic\nvaccine proxy") +
    labs(x = "Cases per 100,000", y = "Under-six fraction", size = "Population")
  figure4 <- add_panel_tag(f4a, "a") | add_panel_tag(f4b, "b")
  save_synthetic(figure4, main_dir, "figure4_age_ecology", "Age-share summaries test the layout only; no age-structured counterfactual was executed.")

  # Main Figure 5: rolling validation baseline --------
  scores <- data.table::melt(
    rolling,
    id.vars = c("test_year", "validation_model"),
    measure.vars = c("total_case_log_score", "typing_log_score", "joint_log_score"),
    variable.name = "component", value.name = "log_score"
  )
  f5a <- ggplot(rolling, aes(observed_total_cases, predicted_total_cases)) +
    geom_abline(slope = 1, intercept = 0, colour = hfmd_palette[["mid"]], linetype = "22", linewidth = 0.4) +
    geom_point(colour = hfmd_palette[["teal"]], size = 1.6) +
    labs(x = "Observed synthetic total", y = "One-step baseline prediction")
  f5b <- ggplot(scores, aes(test_year, log_score, colour = component)) +
    geom_line(linewidth = 0.65) + geom_point(size = 1.15) +
    scale_colour_manual(values = c(total_case_log_score = hfmd_palette[["orange"]], typing_log_score = hfmd_palette[["teal"]], joint_log_score = hfmd_palette[["navy"]]), name = "Baseline score") +
    labs(x = "Test year", y = "Synthetic validation log score")
  figure5 <- add_panel_tag(f5a, "a") / add_panel_tag(f5b, "b") + plot_layout(heights = c(1, 1.2), guides = "collect")
  save_synthetic(figure5, main_dir, "figure5_evidence_boundaries", "A lightweight baseline validates rolling-score plumbing; candidate mechanisms were not fitted.")

  # Supplementary 1: manifest-linked workflow diagram --------
  workflow_nodes <- data.table(
    x = 1:4, label = c("Synthetic data", "Ecological summary", "Dynamics baseline", "Figure contracts"),
    fill = hfmd_workflow_fills
  )
  s1 <- ggplot(workflow_nodes, aes(x, 1)) +
    geom_tile(aes(fill = I(fill)), width = 0.78, height = 0.48, colour = hfmd_palette[["mid"]]) +
    geom_text(aes(label = label), family = hfmd_font_family, size = 2.7) +
    geom_segment(data = workflow_nodes[x < 4], aes(x = x + 0.4, xend = x + 0.6, y = 1, yend = 1), arrow = grid::arrow(length = grid::unit(1.5, "mm"))) +
    coord_cartesian(xlim = c(0.5, 4.5), ylim = c(0.6, 1.4), clip = "off") + theme_hfmd_void()
  save_synthetic(s1, supplementary_dir, "figureS1_analytic_workflow", "Only fully synthetic, receipt-bound validation stages are shown.")

  # Supplementary 2: baseline prediction residuals --------
  residual <- data.table::copy(rolling)
  residual[, residual := observed_total_cases - predicted_total_cases]
  s2a <- ggplot(rolling, aes(test_year, observed_total_cases)) + geom_line(colour = hfmd_palette[["ink"]]) + geom_point(size = 1.2) +
    geom_line(aes(y = predicted_total_cases), colour = hfmd_palette[["teal"]]) + labs(x = "Test year", y = "Synthetic cases")
  s2b <- ggplot(residual, aes(test_year, residual)) + geom_hline(yintercept = 0, linetype = "22", colour = hfmd_palette[["mid"]]) +
    geom_col(fill = hfmd_palette[["orange"]]) + labs(x = "Test year", y = "Baseline residual")
  save_synthetic(add_panel_tag(s2a, "a") | add_panel_tag(s2b, "b"), supplementary_dir, "figureS2_annual_model_fit", "Synthetic one-step baseline only; this is not in-sample formal model fit.")

  # Supplementary 3: region-year contract coverage matrix --------
  s3 <- ggplot(ecological, aes(factor(year), synthetic_region, fill = typing_resolution_fraction)) +
    geom_tile(colour = "white", linewidth = 0.45) +
    scale_fill_gradientn(colours = hfmd_sequential_colours, name = "Typing\nresolution") +
    labs(x = "Year", y = "Fictional region") + theme_hfmd_matrix(border = TRUE)
  save_synthetic(s3, supplementary_dir, "figureS3_contact_matrix", "Contract-coverage matrix placeholder; no contact matrix comparison was performed.")

  # Supplementary 4: synthetic vaccine proxy --------
  s4 <- ggplot(ecological, aes(year, mean_vaccine_proxy, colour = synthetic_region)) + geom_line(linewidth = 0.65) + geom_point(size = 1.1) +
    synthetic_region_scale() +
    labs(x = "Year", y = "Synthetic vaccine proxy", colour = "Fictional region")
  save_synthetic(s4, supplementary_dir, "figureS4_vaccine_proxy", "Fictional exposure values validate temporal alignment only.")

  # Supplementary 5: score-component plumbing --------
  s5 <- ggplot(scores, aes(test_year, log_score, colour = component)) + geom_line(linewidth = 0.65) + geom_point(size = 1.1) +
    facet_wrap(~component, scales = "free_y") + scale_colour_manual(values = c(total_case_log_score = hfmd_palette[["orange"]], typing_log_score = hfmd_palette[["teal"]], joint_log_score = hfmd_palette[["navy"]]), guide = "none") +
    labs(x = "Test year", y = "Synthetic baseline log score")
  save_synthetic(s5, supplementary_dir, "figureS5_bootstrap_estimands", "Score components are shown because bootstrap estimands were intentionally not executed in CI.")

  # Supplementary 6: annual pathogen composition --------
  s6 <- ggplot(pathogen, aes(year, reported_case_fraction, colour = pathogen_group)) + geom_line(linewidth = 0.7) + geom_point(size = 1.2) +
    scale_colour_manual(values = synthetic_pathogen_colours, labels = synthetic_pathogen_labels, name = "Synthetic pathogen group") +
    labs(x = "Year", y = "Synthetic reported-case fraction")
  save_synthetic(s6, supplementary_dir, "figureS6_pathogen_phenology", "Annual composition tests pathogen colour semantics; weekly phenology was not estimated.")

  # Supplementary 7: typing-selection summaries --------
  typing[, not_tested_cases := as.numeric(not_tested_cases)]
  typing_long <- data.table::melt(typing, id.vars = c("synthetic_region", "year"), measure.vars = c("resolved_pathogen_fraction", "not_tested_cases"), variable.name = "metric", value.name = "value")
  s7 <- ggplot(typing_long, aes(year, value, colour = synthetic_region)) + geom_line(linewidth = 0.6) + geom_point(size = 1.0) +
    synthetic_region_scale() +
    facet_wrap(~metric, scales = "free_y") + labs(x = "Year", y = "Synthetic diagnostic", colour = "Fictional region")
  save_synthetic(s7, supplementary_dir, "figureS7_typing_diagnostics", "Observed synthetic testing summaries only; no two-stage selection model was fitted.")

  # Supplementary 8: lightweight residual/completeness diagnostics --------
  s8a <- ggplot(residual, aes(predicted_total_cases, residual)) + geom_hline(yintercept = 0, linetype = "22", colour = hfmd_palette[["mid"]]) +
    geom_point(colour = hfmd_palette[["teal"]], size = 1.5) + labs(x = "Baseline prediction", y = "Residual")
  s8b <- ggplot(ecological, aes(year, weeks_observed, colour = synthetic_region)) + geom_line(linewidth = 0.6) + geom_point(size = 1.0) +
    synthetic_region_scale() +
    labs(x = "Year", y = "Weeks observed", colour = "Fictional region")
  save_synthetic(add_panel_tag(s8a, "a") | add_panel_tag(s8b, "b"), supplementary_dir, "figureS8_ecological_diagnostics", "Diagnostics cover only synthetic summary completeness and the lightweight baseline.")

  # Supplementary 9: validation-model score components, not interactions --------
  s9 <- ggplot(scores, aes(test_year, log_score, colour = component, group = component)) + geom_hline(yintercept = 0, linetype = "22", colour = hfmd_palette[["mid"]]) +
    geom_line(linewidth = 0.65) + geom_point(size = 1.05) + facet_wrap(~validation_model) +
    scale_colour_manual(values = c(total_case_log_score = hfmd_palette[["orange"]], typing_log_score = hfmd_palette[["teal"]], joint_log_score = hfmd_palette[["navy"]]), name = "Baseline component") +
    labs(x = "Test year", y = "Synthetic baseline log score")
  save_synthetic(s9, supplementary_dir, "figureS9_pathogen_pair_structures", "Formal pathogen-pair structures were NOT EXECUTED; this panel validates score-component wiring only.")

  # Supplementary 10: explicit non-execution dashboard --------
  checks <- data.table(
    check = c("Ecological rows", "Pathogen rows", "Typing rows", "Rolling folds"),
    value = c(nrow(ecological), nrow(pathogen), nrow(typing), nrow(rolling)),
    status = "pass"
  )
  checks[, check := factor(check, levels = rev(check))]
  s10 <- ggplot(checks, aes(value, check, colour = status)) + geom_segment(aes(x = 0, xend = value, yend = check), linewidth = 0.55) +
    geom_point(size = 1.8) + geom_text(aes(label = value), hjust = -0.4, family = hfmd_font_family, size = 2.2) +
    scale_colour_manual(values = hfmd_status_colours, guide = "none") +
    scale_x_continuous(expand = expansion(mult = c(0, 0.15))) + labs(x = "Validated synthetic contract rows", y = NULL)
  save_synthetic(s10, supplementary_dir, "figureS10_mechanism_recovery", "Mechanism-recovery simulations were NOT EXECUTED; only input-contract integrity is displayed.")

  main_manifest <- write_figure_manifest(main_dir, paste0("figure", 1:5), require_complete = TRUE)
  supplementary_manifest <- write_figure_manifest(supplementary_dir, paste0("figureS", 1:10), require_complete = TRUE)
  record <- list(
    schema_version = "hfmd-synthetic-figure-render-v1",
    status = "synthetic_validation",
    run_id = run_id,
    profile = profile,
    scientific_inference_allowed = FALSE,
    input_sha256 = setNames(
      vapply(c(ecological_path, pathogen_path, typing_path, rolling_path), sha256_file, character(1)),
      basename(c(ecological_path, pathogen_path, typing_path, rolling_path))
    ),
    main_files = nrow(main_manifest),
    supplementary_files = nrow(supplementary_manifest),
    visual_contract_source = basename(visual_contract_path),
    visual_contract_source_sha256 = render_visual_contract$source_sha256,
    visual_contract_resource_sha256 = render_visual_contract$resource_sha256
  )
  record_path <- file.path(main_dir, "synthetic_render_success.json")
  temporary_record <- paste0(record_path, ".tmp")
  jsonlite::write_json(record, temporary_record, auto_unbox = TRUE, pretty = TRUE)
  Sys.chmod(temporary_record, "0600")
  if (!file.rename(temporary_record, record_path)) stop("Could not atomically publish synthetic render receipt")
  invisible(record)
}

if (sys.nframe() == 0L) {
  all_args <- commandArgs(trailingOnly = FALSE)
  script_arg <- grep("^--file=", all_args, value = TRUE)
  if (!length(script_arg)) stop("Unable to locate render_synthetic_contract.R")
  script_path <- normalizePath(sub("^--file=", "", script_arg[[1L]]), mustWork = TRUE)
  root <- normalizePath(file.path(dirname(script_path), ".."), mustWork = TRUE)
  args <- commandArgs(trailingOnly = TRUE)
  if (length(args) != 3L) {
    stop("Usage: Rscript Script_r/render_synthetic_contract.R RUN_ROOT MAIN_DIR SUPPLEMENTARY_DIR")
  }
  render_synthetic_contract(root, args[[1L]], args[[2L]], args[[3L]])
  message("Rendered 5+10 SYNTHETIC VALIDATION figure bundles inside the run staging root")
}
