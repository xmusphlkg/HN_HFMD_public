# Supporting-table helpers --------
# Shared helpers for the supporting ecological-analysis tables.
# Main and supplementary manuscript figures live under Script_r/figures/.

# package imports --------
suppressPackageStartupMessages({
  library(data.table)
  library(jsonlite)
})

# input-contract reader --------
read_contract <- function(path, required_columns = character()) {
  if (!file.exists(path)) stop("Required analysis output is missing: ", path)
  value <- data.table::fread(path, na.strings = c("", "NA"))
  for (column in intersect(c("county_code", "city_code"), names(value))) {
    data.table::set(value, j = column, value = as.character(value[[column]]))
  }
  absent <- setdiff(required_columns, names(value))
  if (length(absent)) {
    stop("Missing columns in ", basename(path), ": ", paste(absent, collapse = ", "))
  }
  value
}

# manuscript model labels --------
model_label <- function(model_id) {
  labels <- c(
    background_nb2_primary = "Background cases",
    season_outbreak_risk_primary = "Season outbreak risk",
    ignition_cloglog_primary = "Conditional ignition",
    ignition_county_fe_sensitivity = "Conditional ignition (county FE)",
    event_size_nb2_primary = "Event size",
    event_excess_size_nb2 = "Excess event size",
    event_duration_nb2 = "Event duration",
    event_large_logit = "Large outbreak",
    event_growth_wls_exploratory = "Early growth (exploratory)",
    age_target_count_poisson = "Target-age reported cases",
    age_school_age_count_poisson = "School-age reported cases",
    background_population_offset_nb2 = "Background reported-case rate (population offset)",
    background_population_offset_poisson = "Background reported-case rate (Poisson)",
    background_population_offset_count_exposure_poisson = "Background reported-case rate (record-count exposure)",
    background_population_offset_coverage_proxy_poisson = "Background reported-case rate (two-dose coverage proxy)",
    background_population_offset_coverage_proxy_nb2 = "Background reported-case rate (two-dose coverage proxy; NB2)",
    background_population_offset_coverage_proxy_county_trend_poisson = "Background reported-case rate (two-dose coverage proxy; unit trends)",
    background_population_offset_coverage_proxy_weather_poisson = "Background reported-case rate (two-dose coverage proxy; weather-adjusted)",
    background_population_offset_coverage_proxy_weather_nb2 = "Background reported-case rate (two-dose coverage proxy; weather-adjusted NB2)",
    background_population_offset_coverage_proxy_weather_county_trend_poisson = "Background reported-case rate (two-dose coverage proxy; weather and unit trends)",
    background_population_offset_weather_poisson = "Background reported-case rate (weather-adjusted)",
    background_population_offset_count_exposure_weather_poisson = "Background reported-case rate (records; weather-adjusted)",
    background_population_offset_urbanization_poisson = "Background reported-case rate (urbanization-adjusted)",
    background_population_offset_count_exposure_urbanization_poisson = "Background reported-case rate (records; urbanization-adjusted)",
    background_population_offset_urbanization_exclude_2021_poisson = "Background reported-case rate (urbanization-adjusted; exclude 2021)",
    background_population_offset_count_exposure_urbanization_exclude_2021_poisson = "Background reported-case rate (records; urbanization-adjusted; exclude 2021)",
    background_population_offset_exclude_rollout_poisson = "Background reported-case rate (exclude rollout)",
    age_target_population_offset_poisson = "Target-age reported-case rate",
    age_target_population_offset_exclude_rollout_poisson = "Target-age rate (exclude rollout)",
    age_target_population_offset_count_exposure_poisson = "Target-age rate (record-count exposure)",
    age_target_population_offset_count_exposure_exclude_rollout = "Target-age rate (records; exclude rollout)",
    age_target_population_offset_0_4_sensitivity = "Target-age rate (0-4 denominator)",
    age_school_population_offset_poisson = "School-age reported-case rate",
    age_school_population_offset_exclude_rollout_poisson = "School-age rate (exclude rollout)",
    age_target_composition_primary = "Target-age composition",
    pathogen_ev71_typed_primary = "EV-A71 among typed"
  )
  answer <- unname(labels[model_id])
  answer[is.na(answer)] <- gsub("_", " ", model_id[is.na(answer)])
  answer
}
