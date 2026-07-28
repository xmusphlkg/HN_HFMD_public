# Figure S3: contact matrix --------
# Canonical supplementary-figure script; edit this file to change this figure only.

project_root <- normalizePath(getOption("hfmd.project_root", "."), mustWork = TRUE)
if (!file.exists(file.path(project_root, "HFMD.Rproj"))) stop("Set the working directory to the project root before sourcing this figure")
.libPaths(c(file.path(project_root, ".r_library"), .libPaths()))
source(file.path(project_root, "Script_r", "common.R"), local = FALSE)
output_dir <- normalizePath(
  getOption("hfmd.output_dir", file.path(project_root, "Outcome", "figures", "supplementary")),
  mustWork = FALSE
)
invalidate_figure_render_success()

# load derived contact matrix --------
# This fixed input is not evidence of a causal pathway.
contact <- read_figure_data(
  file.path(project_root, "Script_py", "dynamics", "contact_matrix_main.csv"),
  c("source_age", "target_age", "contact_rate_normalized")
)
contact[, source := factor(source_age, levels = age_order, labels = unname(age_labels[age_order]))]
contact[, target := factor(target_age, levels = rev(age_order), labels = rev(unname(age_labels[age_order])))]
# draw supplementary panel --------
figureS3 <- ggplot(contact, aes(x = source, y = target, fill = contact_rate_normalized)) +
  geom_tile(colour = "white", linewidth = 0.55) +
  geom_text(aes(label = sprintf("%.3f", contact_rate_normalized)), family = hfmd_font_family, size = 2.25) +
  scale_fill_gradientn(
    colours = hfmd_sequential_colours,
    labels = scales::label_number(accuracy = 0.01), name = "Relative\ncontact weight"
  ) +
  coord_equal() +
  labs(x = "Infectious age group (years)", y = "Susceptible age group (years)") +
  theme_hfmd_matrix(border = TRUE) +
  theme_hfmd_legend(position = "right")
# save figure --------
save_figure_bundle(figureS3, output_dir, "figureS3_contact_matrix", 7.2, 4.85)
write_figure_manifest(output_dir)
message("Rendered Figure S3: ", output_dir)
