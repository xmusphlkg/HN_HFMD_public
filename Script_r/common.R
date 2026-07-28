# Shared figure utilities --------
# Visual language, data checks, and export functions for every manuscript figure.

# package imports --------
suppressPackageStartupMessages({
  library(data.table)
  library(ggplot2)
  library(patchwork)
})

# visual constants and palette --------
hfmd_font_family <- "DejaVu Sans"
hfmd_png_dpi <- 300
hfmd_tiff_dpi <- 600
hfmd_base_size <- 7.0
hfmd_axis_text_compact_size <- 5.8
hfmd_axis_text_dense_size <- 5.2
hfmd_strip_text_dense_size <- 5.4

hfmd_palette <- c(
  navy = "#123B4A",
  teal = "#2A9D8F",
  pale_teal = "#8CCBC2",
  cream = "#E9D8A6",
  orange = "#E57C23",
  red = "#C65353",
  blue = "#4C78A8",
  ink = "#20272B",
  mid = "#737B80",
  light = "#D8DDDE",
  faint = "#F2F3F2"
)

# Semantic mappings shared by every figure. Keep fixed colours here so that a
# palette change propagates consistently without editing figure-specific code.
pathogen_colours <- c(
  EV_A71 = hfmd_palette[["orange"]],
  CV_A16 = hfmd_palette[["teal"]],
  other_enterovirus = hfmd_palette[["navy"]]
)
pathogen_labels <- c(
  EV_A71 = "EV-A71",
  CV_A16 = "CV-A16",
  other_enterovirus = "Other enteroviruses"
)
age_order <- c("lt1", "age1_2", "age3_5", "age6_14", "age15plus")
age_labels <- c(lt1 = "<1", age1_2 = "1-2", age3_5 = "3-5", age6_14 = "6-14", age15plus = "15+")
age_colours <- c(
  `<1` = hfmd_palette[["blue"]],
  `1-2` = hfmd_palette[["orange"]],
  `3-5` = hfmd_palette[["teal"]],
  `6-14` = hfmd_palette[["mid"]],
  `15+` = hfmd_palette[["ink"]]
)
hfmd_sequential_colours <- c("#F5F0E2", "#A7D6CD", "#3A9B91", hfmd_palette[["navy"]])
hfmd_workflow_fills <- c("#E8F1F8", "#E6F3EE", "#FFF2D9", "#F9E6E3")
hfmd_status_colours <- c(
  pass = hfmd_palette[["teal"]],
  supports = hfmd_palette[["teal"]],
  stable = hfmd_palette[["navy"]],
  attenuated = hfmd_palette[["cream"]],
  warning = hfmd_palette[["orange"]],
  reversed = hfmd_palette[["red"]],
  fail = hfmd_palette[["red"]],
  boundary = hfmd_palette[["orange"]],
  not_estimated = hfmd_palette[["light"]]
)

# shared ggplot theme --------
theme_hfmd <- function(base_size = hfmd_base_size, base_family = hfmd_font_family) {
  theme_classic(base_size = base_size, base_family = base_family) +
    theme(
      text = element_text(family = base_family, colour = hfmd_palette[["ink"]]),
      plot.title = element_blank(),
      plot.subtitle = element_blank(),
      plot.caption = element_blank(),
      plot.tag = element_text(face = "bold", size = 8.2, hjust = 0, vjust = 1),
      plot.tag.position = "topleft",
      axis.title = element_text(face = "bold", size = rel(0.94)),
      axis.text = element_text(colour = hfmd_palette[["ink"]], size = rel(0.88)),
      axis.line = element_line(colour = hfmd_palette[["ink"]], linewidth = 0.35),
      axis.ticks = element_line(colour = hfmd_palette[["ink"]], linewidth = 0.32),
      axis.ticks.length = grid::unit(1.2, "mm"),
      legend.position = "bottom",
      legend.key.height = grid::unit(3.2, "mm"),
      legend.key.width = grid::unit(3.2, "mm"),
      legend.title = element_text(face = "bold", size = rel(0.82), lineheight = 0.92),
      legend.text = element_text(size = rel(0.74)),
      strip.background = element_blank(),
      strip.text = element_text(face = "bold", size = rel(0.92)),
      panel.grid = element_blank(),
      plot.margin = margin(5, 6, 5, 6)
    )
}

# Theme variants only encode structural differences. Typography remains owned
# by theme_hfmd() so legend and text styling cannot drift between figures.
theme_hfmd_legend <- function(
    position = "bottom", inside = NULL, justification = NULL,
    background_alpha = NULL) {
  elements <- list(legend.position = position)
  if (!is.null(inside)) elements$legend.position.inside <- inside
  if (!is.null(justification)) elements$legend.justification <- justification
  if (!is.null(background_alpha)) {
    elements$legend.background <- element_rect(
      fill = scales::alpha("white", background_alpha), colour = NA
    )
  }
  do.call(theme, elements)
}

theme_hfmd_matrix <- function(border = FALSE) {
  elements <- list(
    axis.line = element_blank(),
    axis.ticks = element_blank()
  )
  if (isTRUE(border)) {
    elements$panel.border <- element_rect(
      fill = NA, colour = hfmd_palette[["ink"]], linewidth = 0.35
    )
  }
  do.call(theme, elements)
}

theme_hfmd_rotated_x <- function(angle = 30, hjust = 1, vjust = 1) {
  theme(axis.text.x = element_text(angle = angle, hjust = hjust, vjust = vjust))
}

theme_hfmd_void <- function(base_family = hfmd_font_family) {
  theme_void(base_size = hfmd_base_size, base_family = base_family) +
    theme(
      text = element_text(family = base_family, colour = hfmd_palette[["ink"]]),
      plot.margin = margin(5, 6, 5, 6)
    )
}

# Every canonical figure script sources this file, which resets ggplot to the
# same Figure 1 visual grammar before any plot objects are created.
hfmd_figure_theme <- theme_hfmd()
invisible(theme_set(hfmd_figure_theme))

# visual contract and run context --------
hfmd_truthy <- function(value) {
  tolower(trimws(as.character(value))) %in% c("1", "true", "yes", "on")
}

hfmd_is_formal_mode <- function() {
  hfmd_truthy(Sys.getenv("HFMD_FORMAL", unset = "false")) ||
    identical(tolower(Sys.getenv("HFMD_PROFILE", unset = "")), "restricted")
}

require_hfmd_run_id <- function(always = FALSE) {
  run_id <- trimws(Sys.getenv("HFMD_RUN_ID", unset = ""))
  required <- isTRUE(always) || hfmd_is_formal_mode()
  if (required && !nzchar(run_id)) {
    stop("HFMD_RUN_ID is required for formal or run-scoped figure rendering")
  }
  if (nzchar(run_id) && !grepl(
    "^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}(?:-[a-z0-9-]{1,33})?$",
    run_id, perl = TRUE
  )) {
    stop("Invalid HFMD_RUN_ID: ", run_id)
  }
  run_id
}

assert_hfmd_run_scoped_path <- function(path, run_id = require_hfmd_run_id(always = TRUE)) {
  resolved <- normalizePath(path, mustWork = TRUE)
  components <- strsplit(resolved, .Platform$file.sep, fixed = TRUE)[[1L]]
  if (!run_id %in% components) stop("Path is not scoped beneath HFMD_RUN_ID: ", resolved)
  if (any(components %in% c("AnalysisOutput", "Outcome"))) {
    stop("Run-scoped rendering refuses legacy AnalysisOutput/Outcome paths")
  }
  resolved
}

assert_hfmd_run_scoped_output_path <- function(path, run_id = require_hfmd_run_id(always = TRUE)) {
  resolved <- normalizePath(path, mustWork = FALSE)
  components <- strsplit(resolved, .Platform$file.sep, fixed = TRUE)[[1L]]
  if (!run_id %in% components) stop("Output path is not scoped beneath HFMD_RUN_ID: ", resolved)
  if (any(components %in% c("AnalysisOutput", "Outcome"))) {
    stop("Run-scoped rendering refuses legacy AnalysisOutput/Outcome outputs")
  }
  resolved
}

invalidate_figure_render_success <- function() {
  path <- getOption("hfmd.render_success_path", "")
  if (is.null(path) || length(path) != 1L || !nzchar(path)) return(invisible(FALSE))
  run_id <- require_hfmd_run_id(always = TRUE)
  safe_path <- assert_hfmd_run_scoped_output_path(path, run_id)
  if (file.exists(safe_path) && !file.remove(safe_path)) {
    stop("Could not invalidate stale render-success record: ", safe_path)
  }
  invisible(TRUE)
}

find_hfmd_project_root <- function() {
  configured <- getOption("hfmd.project_root", NULL)
  if (!is.null(configured) && nzchar(configured)) {
    return(normalizePath(configured, mustWork = TRUE))
  }
  for (frame in rev(sys.frames())) {
    if (exists("project_root", envir = frame, inherits = FALSE)) {
      candidate <- get("project_root", envir = frame, inherits = FALSE)
      if (length(candidate) == 1L && file.exists(file.path(candidate, "HFMD.Rproj"))) {
        return(normalizePath(candidate, mustWork = TRUE))
      }
    }
  }
  candidate <- normalizePath(".", mustWork = TRUE)
  if (!file.exists(file.path(candidate, "HFMD.Rproj"))) {
    stop("Cannot locate the HFMD project root for the visual contract")
  }
  candidate
}

hfmd_visual_contract_path <- function() {
  configured <- Sys.getenv("HFMD_VISUAL_CONTRACT", unset = "")
  if (!nzchar(configured)) configured <- getOption("hfmd.visual_contract", "")
  if (nzchar(configured)) return(normalizePath(configured, mustWork = TRUE))
  normalizePath(
    file.path(find_hfmd_project_root(), "config", "visual_contract.yaml"),
    mustWork = TRUE
  )
}

visual_contract_for_render <- function(root) {
  configured <- Sys.getenv("HFMD_VISUAL_CONTRACT", unset = "")
  if (nzchar(configured)) return(normalizePath(configured, mustWork = TRUE))
  if (hfmd_is_formal_mode()) {
    stop("Formal rendering requires HFMD_VISUAL_CONTRACT to point to the run-scoped snapshot")
  }
  normalizePath(file.path(root, "config", "visual_contract.yaml"), mustWork = TRUE)
}

unquote_yaml_scalar <- function(value) {
  value <- trimws(value)
  if (nchar(value) >= 2L && substr(value, 1L, 1L) %in% c("\"", "'") &&
      substr(value, nchar(value), nchar(value)) == substr(value, 1L, 1L)) {
    return(substr(value, 2L, nchar(value) - 1L))
  }
  value
}

finalize_hfmd_visual_contract <- function(figures, path, resource_sha256 = NULL) {
  if (length(figures) != 15L) stop("Visual contract must declare 5 main and 10 supplementary figures")
  ids <- names(figures)
  if (!identical(ids[seq_len(5L)], paste0("figure", seq_len(5L)))) {
    stop("Main figure IDs are not ordered figure1 through figure5")
  }
  if (!identical(ids[6:15], paste0("figureS", seq_len(10L)))) {
    stop("Supplementary figure IDs are not ordered figureS1 through figureS10")
  }
  required <- c("figure_id", "output_name", "width_in", "height_in", "export_formats")
  for (entry in figures) {
    absent <- setdiff(required, names(entry))
    if (length(absent)) stop("Visual contract entry ", entry$figure_id, " lacks: ", paste(absent, collapse = ", "))
    if (!is.finite(entry$width_in) || !is.finite(entry$height_in) || entry$width_in <= 0 || entry$height_in <= 0) {
      stop("Invalid export dimensions for ", entry$figure_id)
    }
  }
  allowed_formats <- c("pdf", "svg", "png", "tiff")
  invalid_formats <- setdiff(unique(unlist(lapply(figures, `[[`, "export_formats"))), allowed_formats)
  if (length(invalid_formats)) stop("Unsupported visual-contract formats: ", paste(invalid_formats, collapse = ", "))
  output_names <- vapply(figures, `[[`, character(1), "output_name")
  if (anyDuplicated(output_names)) stop("Visual-contract output_name values must be unique")
  source_sha256 <- sha256_file(path)
  structure(
    list(
      path = path,
      sha256 = source_sha256,
      source_sha256 = source_sha256,
      resource_sha256 = resource_sha256 %||% source_sha256,
      figures = figures
    ),
    class = "hfmd_visual_contract"
  )
}

# Parse either the source YAML or the immutable JSON configuration snapshot.
# This keeps the plotting runtime locked to its current package set; schema
# validation in Python remains authoritative for the complete document.
read_hfmd_visual_contract <- function(path = hfmd_visual_contract_path()) {
  path <- normalizePath(path, mustWork = TRUE)
  if (grepl("[.]json$", path, ignore.case = TRUE)) {
    document <- jsonlite::fromJSON(path, simplifyVector = FALSE)
    resource <- if (!is.null(document$resources$visual_contract)) {
      document$resources$visual_contract
    } else if (!is.null(document$main_figures) && !is.null(document$supplementary_figures)) {
      document
    } else {
      stop("JSON visual contract must be a config snapshot or a direct visual-contract document")
    }
    raw_figures <- c(resource$main_figures, resource$supplementary_figures)
    figures <- list()
    for (index in seq_along(raw_figures)) {
      raw <- raw_figures[[index]]
      entry <- list(
        figure_id = as.character(raw$figure_id),
        output_name = as.character(raw$output_name),
        source_script = as.character(raw$source_script),
        width_in = as.numeric(raw$width_in),
        height_in = as.numeric(raw$height_in),
        export_formats = tolower(as.character(unlist(raw$export_formats))),
        implementation_status = as.character(raw$implementation_status),
        section = if (index <= length(resource$main_figures)) "main" else "supplementary"
      )
      if (!is.null(raw$legacy_design_source)) entry$legacy_design_source <- as.character(raw$legacy_design_source)
      figures[[entry$figure_id]] <- entry
    }
    resource_hash <- NULL
    if (!is.null(document$source_hashes[["visual_contract.yaml"]])) {
      resource_hash <- as.character(document$source_hashes[["visual_contract.yaml"]])
    }
    return(finalize_hfmd_visual_contract(figures, path, resource_hash))
  }
  lines <- readLines(path, warn = FALSE, encoding = "UTF-8")
  section <- NA_character_
  current <- NULL
  figures <- list()

  store_current <- function(value) {
    if (is.null(value)) return(invisible(NULL))
    required <- c("figure_id", "output_name", "width_in", "height_in", "export_formats")
    absent <- setdiff(required, names(value))
    if (length(absent)) {
      stop("Visual contract entry ", value$figure_id %||% "<unknown>",
           " lacks: ", paste(absent, collapse = ", "))
    }
    value$width_in <- as.numeric(value$width_in)
    value$height_in <- as.numeric(value$height_in)
    if (!is.finite(value$width_in) || !is.finite(value$height_in) ||
        value$width_in <= 0 || value$height_in <= 0) {
      stop("Invalid export dimensions for ", value$figure_id)
    }
    value$section <- section
    figures[[value$figure_id]] <<- value
    invisible(NULL)
  }

  for (line in lines) {
    if (identical(trimws(line), "main_figures:")) {
      store_current(current)
      current <- NULL
      section <- "main"
      next
    }
    if (identical(trimws(line), "supplementary_figures:")) {
      store_current(current)
      current <- NULL
      section <- "supplementary"
      next
    }
    id_match <- regexec("^  - figure_id:[[:space:]]*([^[:space:]#]+)", line)
    id_parts <- regmatches(line, id_match)[[1L]]
    if (length(id_parts)) {
      store_current(current)
      current <- list(figure_id = unquote_yaml_scalar(id_parts[[2L]]))
      next
    }
    if (is.null(current)) next
    field_match <- regexec(
      "^    (output_name|source_script|legacy_design_source|width_in|height_in|implementation_status|export_formats):[[:space:]]*(.*)$",
      line
    )
    field_parts <- regmatches(line, field_match)[[1L]]
    if (!length(field_parts)) next
    key <- field_parts[[2L]]
    value <- trimws(field_parts[[3L]])
    if (identical(key, "export_formats")) {
      value <- sub("^\\[", "", sub("\\]$", "", value))
      value <- trimws(strsplit(value, ",", fixed = TRUE)[[1L]])
      value <- unname(tolower(vapply(value, unquote_yaml_scalar, character(1))))
    } else {
      value <- unquote_yaml_scalar(value)
    }
    current[[key]] <- value
  }
  store_current(current)

  finalize_hfmd_visual_contract(figures, path)
}

`%||%` <- function(left, right) if (is.null(left) || !length(left)) right else left

resolve_figure_output_name <- function(name) {
  overrides <- getOption("hfmd.output_name_override", character())
  if (length(overrides) && !is.null(names(overrides)) && name %in% names(overrides)) {
    return(unname(overrides[[name]]))
  }
  name
}

figure_contract_entry <- function(name, contract = read_hfmd_visual_contract()) {
  resolved <- resolve_figure_output_name(name)
  matches <- vapply(contract$figures, function(entry) identical(entry$output_name, resolved), logical(1))
  if (sum(matches) != 1L) {
    stop("Figure output is not uniquely registered in visual_contract.yaml: ", resolved)
  }
  contract$figures[[which(matches)]]
}

# input readers and validation --------
read_figure_data <- function(
    path, required_columns = character(),
    expected_run_id = require_hfmd_run_id()) {
  if (!file.exists(path)) stop("Required figure source is missing: ", path)
  value <- if (grepl("[.]gz$", path, ignore.case = TRUE)) {
    data.table::as.data.table(utils::read.csv(
      gzfile(path), stringsAsFactors = FALSE, na.strings = c("", "NA")
    ))
  } else {
    data.table::fread(path, na.strings = c("", "NA"))
  }
  absent <- setdiff(required_columns, names(value))
  if (length(absent)) {
    stop("Missing columns in ", basename(path), ": ", paste(absent, collapse = ", "))
  }
  if (nzchar(expected_run_id)) {
    if (!"run_id" %in% names(value)) {
      stop("Figure source lacks required run_id contract: ", path)
    }
    observed_run_ids <- unique(as.character(value[["run_id"]]))
    if (length(observed_run_ids) != 1L || observed_run_ids[[1L]] != expected_run_id) {
      stop(
        "Figure source run_id mismatch for ", path,
        "; expected ", expected_run_id,
        ", observed ", paste(observed_run_ids, collapse = ", ")
      )
    }
  }
  value
}

hfmd_run_scoped_result_dir <- function() {
  configured <- getOption("hfmd.result_dir", Sys.getenv("HFMD_RESULT_DIR", unset = ""))
  if (is.null(configured) || length(configured) != 1L || !nzchar(configured)) {
    stop("A run-scoped result directory is required via hfmd.result_dir or HFMD_RESULT_DIR")
  }
  root <- normalizePath(configured, mustWork = TRUE)
  run_id <- require_hfmd_run_id(always = TRUE)
  assert_hfmd_run_scoped_path(root, run_id)
}

read_run_scoped_figure_contract <- function(
    result_dir, filename, required_columns = character()) {
  run_id <- require_hfmd_run_id(always = TRUE)
  if (basename(filename) != filename || grepl("[\\/]", filename)) {
    stop("Figure-data contract filename must not contain directories: ", filename)
  }
  root <- assert_hfmd_run_scoped_path(result_dir, run_id)
  contract_dir <- normalizePath(file.path(root, "figure_data"), mustWork = TRUE)
  path <- normalizePath(file.path(contract_dir, filename), mustWork = TRUE)
  if (!startsWith(path, paste0(contract_dir, .Platform$file.sep))) {
    stop("Figure-data contract escaped the run-scoped figure_data directory")
  }
  value <- read_figure_data(
    path,
    unique(c("run_id", "parent_manifest_sha256", required_columns)),
    expected_run_id = run_id
  )
  parent_hashes <- unique(as.character(value$parent_manifest_sha256))
  if (length(parent_hashes) != 1L || !grepl("^[0-9a-f]{64}$", parent_hashes[[1L]])) {
    stop("Figure-data contract must carry one valid parent_manifest_sha256: ", path)
  }
  value
}

require_figure_panels <- function(value, panels, source_name) {
  observed <- unique(as.character(value$panel))
  missing <- setdiff(panels, observed)
  extra <- setdiff(observed, panels)
  if (length(missing) || length(extra)) {
    stop(
      source_name, " panel contract mismatch; missing=",
      paste(missing, collapse = ","), "; extra=", paste(extra, collapse = ",")
    )
  }
  invisible(TRUE)
}

read_counterfactual_figure_data <- function(result_dir) {
  value <- read_figure_data(
    file.path(result_dir, "counterfactual_week_age_pathogen.csv.gz"),
    c("scenario", "week_start", "age_group", "pathogen_group", "expected_reported_cases")
  )
  value[, week_start := as.Date(week_start)]
  value
}

read_counterfactual_estimands <- function(result_dir) {
  read_figure_data(
    file.path(result_dir, "counterfactual_estimands.csv"),
    c("scope", "estimand", "estimate", "bootstrap_low", "bootstrap_high")
  )
}

# panel-label and number-format helpers --------
with_graphics_device <- function(open_device, plot) {
  open_device()
  device <- grDevices::dev.cur()
  on.exit({
    devices <- grDevices::dev.list()
    if (!is.null(devices) && device %in% devices) grDevices::dev.off(device)
  }, add = TRUE)
  print(plot)
  grDevices::dev.off(device)
}

strip_panel_heading <- function(plot) {
  plot +
    labs(title = NULL, subtitle = NULL, caption = NULL) +
    theme(
      plot.title = element_blank(),
      plot.subtitle = element_blank(),
      plot.caption = element_blank()
    )
}

add_panel_tag <- function(plot, tag) {
  strip_panel_heading(plot) +
    labs(tag = tag)
}

format_direct_number <- function(x, accuracy = 0.1) {
  scales::label_number(accuracy = accuracy, big.mark = ",", trim = TRUE)(x)
}

# save figure bundle --------
save_figure_bundle <- function(plot, output_dir, name, width = NULL, height = NULL) {
  require_hfmd_run_id()
  dir.create(output_dir, recursive = TRUE, showWarnings = FALSE, mode = "0700")
  contract <- read_hfmd_visual_contract()
  entry <- figure_contract_entry(name, contract)
  output_name <- entry$output_name
  width <- entry$width_in
  height <- entry$height_in
  formats <- entry$export_formats
  paths <- setNames(file.path(output_dir, paste0(output_name, ".", formats)), formats)

  if ("pdf" %in% formats) {
    with_graphics_device(
      function() grDevices::cairo_pdf(
        paths[["pdf"]], width = width, height = height, family = hfmd_font_family,
        bg = "white", onefile = TRUE
      ),
      plot
    )
  }
  if ("svg" %in% formats) {
    with_graphics_device(
      function() grDevices::svg(
        paths[["svg"]], width = width, height = height, family = hfmd_font_family,
        bg = "white", onefile = TRUE
      ),
      plot
    )
  }
  if ("png" %in% formats) {
    with_graphics_device(
      function() grDevices::png(
        paths[["png"]], width = width, height = height, units = "in",
        res = getOption("hfmd.png_dpi", hfmd_png_dpi),
        type = "cairo", family = hfmd_font_family, bg = "white"
      ),
      plot
    )
  }
  if ("tiff" %in% formats) {
    with_graphics_device(
      function() grDevices::tiff(
        paths[["tiff"]], width = width, height = height, units = "in",
        res = getOption("hfmd.tiff_dpi", hfmd_tiff_dpi), compression = "lzw",
        type = "cairo", family = hfmd_font_family, bg = "white"
      ),
      plot
    )
  }

  Sys.chmod(unname(paths), mode = "0600")
  invisible(paths)
}

# write output manifest --------
sha256_file <- function(path) {
  output <- system2("sha256sum", shQuote(path), stdout = TRUE, stderr = TRUE)
  status <- attr(output, "status")
  if (!is.null(status) && status != 0L) {
    stop("sha256sum failed for ", path, ": ", paste(output, collapse = "\n"))
  }
  digest <- sub("[[:space:]].*$", "", output[[1L]])
  if (!grepl("^[0-9a-f]{64}$", digest)) stop("Invalid SHA-256 output for ", path)
  digest
}

validate_figure_output_set <- function(output_dir, figure_ids) {
  contract <- read_hfmd_visual_contract()
  entries <- contract$figures[figure_ids]
  if (any(vapply(entries, is.null, logical(1)))) {
    stop("Unknown figure IDs requested for output validation")
  }
  expected <- sort(unlist(lapply(entries, function(entry) {
    paste0(entry$output_name, ".", entry$export_formats)
  })))
  observed <- sort(list.files(
    output_dir,
    pattern = "^[Ff]igure.*[.](pdf|svg|png|tiff)$",
    full.names = FALSE
  ))
  missing <- setdiff(expected, observed)
  extra <- setdiff(observed, expected)
  if (length(missing) || length(extra)) {
    stop(
      "Figure output set differs from visual contract; missing=",
      paste(missing, collapse = ","), "; extra=", paste(extra, collapse = ",")
    )
  }
  invisible(TRUE)
}

write_figure_manifest <- function(output_dir, figure_ids = NULL, require_complete = FALSE) {
  contract <- read_hfmd_visual_contract()
  if (isTRUE(require_complete)) {
    if (is.null(figure_ids) || !length(figure_ids)) {
      stop("figure_ids are required for complete output-set validation")
    }
    validate_figure_output_set(output_dir, figure_ids)
  }
  files <- sort(list.files(
    output_dir,
    pattern = "^[Ff]igure.*[.](pdf|svg|png|tiff)$",
    full.names = TRUE
  ))
  if (!length(files)) stop("No figure outputs found in ", output_dir)
  stems <- sub("[.](pdf|svg|png|tiff)$", "", basename(files))
  formats <- sub("^.*[.]", "", basename(files))
  matched <- lapply(stems, function(stem) {
    hit <- Filter(function(entry) identical(entry$output_name, stem), contract$figures)
    if (length(hit) != 1L) stop("Unregistered figure output in manifest: ", stem)
    hit[[1L]]
  })
  info <- file.info(files)
  manifest <- data.table::data.table(
    file = basename(files),
    figure_id = vapply(matched, `[[`, character(1), "figure_id"),
    format = formats,
    width_in = vapply(matched, `[[`, numeric(1), "width_in"),
    height_in = vapply(matched, `[[`, numeric(1), "height_in"),
    run_id = require_hfmd_run_id(),
    visual_contract_source_sha256 = contract$source_sha256,
    visual_contract_resource_sha256 = contract$resource_sha256,
    bytes = as.numeric(info$size),
    sha256 = vapply(files, sha256_file, character(1))
  )
  manifest_path <- file.path(output_dir, "figure_manifest.csv")
  data.table::fwrite(manifest, manifest_path)
  Sys.chmod(manifest_path, mode = "0600")
  invisible(manifest)
}

# sensitivity display labels --------
sensitivity_display_labels <- c(
  reporting_0.01 = "Reporting fraction: 0.01",
  reporting_0.10 = "Reporting fraction: 0.10",
  cross_duration_3.31w = "Heterotypic duration: 3.31 weeks",
  cross_duration_23.4w = "Heterotypic duration: 23.4 weeks",
  cross_strength_fixed_0.37 = "Heterotypic strength: 0.37",
  cross_strength_fixed_0.68 = "Heterotypic strength: 0.68",
  cross_strength_fixed_0.96 = "Heterotypic strength: 0.96",
  homologous_half_life_104w = "Same-pathogen immunity: 104 weeks",
  homologous_half_life_520w = "Same-pathogen immunity: 520 weeks",
  generation_one_week = "Generation kernel: one week",
  generation_three_week = "Generation kernel: three weeks",
  coverage_r10 = "Completion deduction: 10%",
  coverage_r25 = "Completion deduction: 25%",
  coverage_r50 = "Completion deduction: 50%",
  vaccine_efficacy_low = "Two-dose effectiveness: 0.752",
  vaccine_efficacy_high = "Two-dose effectiveness: 0.900",
  population_minus_10pct = "Population: -10%",
  population_plus_10pct = "Population: +10%",
  typed_ev_overascertain_1.5 = "EV-A71 typing ratio: 1.50",
  typed_ev_underascertain_0.67 = "EV-A71 typing ratio: 0.67"
)
