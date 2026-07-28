# Figure S1: analytic workflow --------
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

# define workflow nodes --------
# Analytical pathway and inferential boundary.
boxes <- data.table(
  xmin = c(0.02, 0.27, 0.52, 0.77), xmax = c(0.23, 0.48, 0.73, 0.98),
  fill = hfmd_workflow_fills,
  panel = c("a", "b", "c", "d"),
  body = c(
    "Weekly total reports\nSparse pathogen typing\nPopulation and age mixing\nEcological vaccine exposure",
    "Trailing pathogen-share estimate\nThree pathogen groups\nInfection-pressure history\nHomologous immunity and\nheterotypic protection",
    "Five age groups\nJoint total-case and\ntyping likelihood\nSeasonality and residual\npandemic-period transmission",
    "Paired vaccination and\nno-vaccination histories\nAdditional proxies and net benefit\nBootstrap and sensitivity\nTemporal evaluation"
  )
)
# draw workflow schematic --------
figureS1 <- ggplot() +
  geom_rect(
    data = boxes, aes(xmin = xmin, xmax = xmax, ymin = 0.30, ymax = 0.90, fill = I(fill)),
    colour = hfmd_palette[["mid"]], linewidth = 0.35
  ) +
  geom_text(
    data = boxes, aes(x = xmin + 0.015, y = 0.855, label = panel),
    hjust = 0, family = hfmd_font_family, fontface = "bold", size = 2.8
  ) +
  geom_text(
    data = boxes, aes(x = (xmin + xmax) / 2, y = 0.59, label = body),
    family = hfmd_font_family, lineheight = 1.04, size = 1.95
  ) +
  geom_segment(
    data = data.table(x = c(0.235, 0.485, 0.735), xend = c(0.265, 0.515, 0.765)),
    aes(x = x, xend = xend, y = 0.60, yend = 0.60),
    arrow = grid::arrow(length = grid::unit(1.7, "mm"), type = "closed"),
    colour = hfmd_palette[["mid"]], linewidth = 0.45
  ) +
  annotate(
    "rect", xmin = 0.13, xmax = 0.87, ymin = 0.08, ymax = 0.20,
    fill = hfmd_palette[["faint"]], colour = hfmd_palette[["mid"]], linewidth = 0.32
  ) +
  annotate(
    "text", x = 0.5, y = 0.14,
    label = "Scientific contrast: a larger non-EV-A71 share is not equivalent to more\nnon-EV-A71 reported-case proxies",
    family = hfmd_font_family, fontface = "bold", size = 2.25, lineheight = 1.0
  ) +
  coord_cartesian(xlim = c(0, 1), ylim = c(0, 1), expand = FALSE, clip = "off") +
  theme_hfmd_void()
# save figure --------
save_figure_bundle(figureS1, output_dir, "figureS1_analytic_workflow", 7.2, 4.25)
write_figure_manifest(output_dir)
message("Rendered Figure S1: ", output_dir)
