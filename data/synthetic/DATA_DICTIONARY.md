# Synthetic data dictionary

All regions, counts and exposures are generated. No value is derived from the
restricted Hunan records.

## `weekly_surveillance.csv`

| Field | Meaning |
|---|---|
| `synthetic_region` | Fictional region name |
| `year`, `iso_week` | Synthetic calendar indices |
| `age_group` | Generated age stratum |
| `pathogen_group` | EV-A71, CV-A16 or other enterovirus |
| `severity_group` | Generated severe/non-severe stratum |
| `cases` | Generated reported-case count |
| `typed_cases` | Generated cases with a resolved pathogen label |
| `population` | Fictional region population |
| `ev_a71_vaccine_proxy` | Generated sigmoid exposure between 0 and 1 |

## `typing_selection.csv`

Long-form decomposition of the same reported cases by fictional region, week,
age, severity, case class, testing stage and resolved pathogen. The reproduction
script verifies that annual totals equal `weekly_surveillance.csv` and that
resolved pathogen totals equal its `typed_cases`.

## `region_metadata.csv`

Fictional population scale and generated climate index for eight regions.

## `contact_matrix.csv`

Generated age-to-age contact rates for five age groups.
