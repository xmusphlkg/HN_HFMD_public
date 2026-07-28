# Reproducible execution environment

The canonical runtime is Python 3.13.5, R 4.5.0, `uv` 0.11.29, Snakemake
9.23.1, UTC, the `C.UTF-8` locale, one BLAS thread, and DejaVu Sans. Python
packages are fixed by `uv.lock`; R packages are fixed by
`Script_r/renv.lock`.

## Native environment

```bash
uv sync --locked --extra analysis --extra workflow --extra dev
Rscript -e 'dir.create(".r_library", showWarnings = FALSE); install.packages("https://cloud.r-project.org/src/contrib/Archive/renv/renv_1.2.3.tar.gz", repos=NULL, lib=".r_library"); renv::restore(lockfile="Script_r/renv.lock", library=".r_library", prompt=FALSE)'
uv run --locked hfmd config validate --profile synthetic
uv run --locked hfmd run --target all --profile ci
```

The `ci` and `synthetic` profiles do not require Pandoc: their editable DOCX
files are generated directly and are stamped as synthetic validation only. The
`restricted` profile requires Pandoc and refuses formal publication unless the
Git worktree is clean, all restricted inputs are registered, all scientific
adapters have passed, and author-supplied submission metadata are present.

## OCI image

`Containerfile` pins the base image by digest and verifies SHA-256 hashes for
the R 4.5.0 source archive and Pandoc 3.10 package. It currently targets
`linux/amd64`.

```bash
docker build --platform linux/amd64 -f Containerfile -t hfmd:locked .
docker run --rm hfmd:locked config validate --profile synthetic
```

The build context excludes the entire `AnalysisData/` tree, raw data,
previous results, runtime candidates, caches, secrets, and local environments
via `.dockerignore`.
Formal restricted runs therefore require a separately mounted, authorized
data volume and are never performed during the image build or public CI.

The image never copies the private `.git` history. After dependencies are
installed, it creates a deterministic, source-only Git commit from the public
build context so candidate manifests can still record a clean commit and tree.

## Deterministic controls

- `TZ=UTC`, `LANG/LC_ALL=C.UTF-8`, and `PYTHONHASHSEED=0` are fixed.
- OpenMP and common BLAS thread variables are fixed to one.
- Every run snapshots canonical configuration and records code, input,
  environment, seed, thread, receipt, and output hashes.
- Gzip-producing code must use `mtime=0`; run publication validates the exact
  file set and rejects stale or extra files.
- GitHub Actions runs only synthetic data with two cores and never receives
  restricted credentials or inputs.
