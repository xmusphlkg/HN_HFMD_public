# Supporting-table formatting --------
# Format individual standardized model outputs for manuscript-ready tables.
# format one model table --------
format_model_table <- function(input_path, output_path) {
  table <- read_contract(input_path, c("model_id", "outcome", "analysis", "term", "effect", "effect_low", "effect_high", "effect_scale", "n_obs", "n_clusters", "cluster_unit"))
  if (!nrow(table)) {
    fwrite(table, output_path)
    return(invisible(table))
  }
  table[, model := model_label(model_id)]
  table[, estimate_95_ci := sprintf("%.3f (%.3f to %.3f)", effect, effect_low, effect_high)]
  formatted <- table[, .(model, outcome, analysis, term, effect_scale, estimate_95_ci, n_obs, n_clusters, cluster_unit, n_years, status)]
  fwrite(formatted, output_path, na = "")
  Sys.chmod(output_path, mode = "0600")
  invisible(formatted)
}

# write all supporting tables --------
make_publication_tables <- function(paths) {
  format_model_table(file.path(paths$tables, "primary_models.csv"), file.path(paths$publication_tables, "table_2_primary_models.csv"))
  format_model_table(file.path(paths$tables, "outbreak_models.csv"), file.path(paths$publication_tables, "table_3_outbreak_models.csv"))
  format_model_table(file.path(paths$tables, "mechanism_models.csv"), file.path(paths$publication_tables, "table_4_mechanism_models.csv"))
  format_model_table(file.path(paths$tables, "sensitivity_models.csv"), file.path(paths$publication_tables, "table_s1_sensitivity_models.csv"))
  file.copy(file.path(paths$tables, "counterfactual.csv"), file.path(paths$publication_tables, "table_s2_counterfactual_models.csv"), overwrite = TRUE)
  file.copy(file.path(paths$tables, "sample_flow.csv"), file.path(paths$publication_tables, "table_1_sample_flow.csv"), overwrite = TRUE)
  file.copy(file.path(paths$tables, "descriptive.csv"), file.path(paths$publication_tables, "table_1_descriptive.csv"), overwrite = TRUE)
  Sys.chmod(list.files(paths$publication_tables, full.names = TRUE), mode = "0600")
}
