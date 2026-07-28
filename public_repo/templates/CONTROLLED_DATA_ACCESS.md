# Controlled data access

The public repository cannot provide the restricted surveillance, outbreak,
vaccination, exact small-area population, or other licensed inputs used in the
Hunan analysis. Qualified researchers must apply to the responsible data
controller and satisfy the controller's applicable access conditions.

The `public_data/` directory provides only a disclosure-selected set of
province-level and model-summary result tables. These tables do not replace the
restricted source data and cannot reproduce the county-level or weekly
analysis.

An approved user should restore source files only inside the authorized
restricted environment, verify them against the project input manifest, and
run the `restricted` workflow profile. Raw data must not be copied into the
public repository, CI artifacts, issue attachments, logs, or external runners.

The controller, application route, and access conditions must be supplied by
the study authors before publication. This file does not invent or imply
approval by any organization.
