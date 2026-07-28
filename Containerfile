# syntax=docker/dockerfile:1.7

# Multi-architecture manifest digest resolved for python:3.13.5-bookworm on
# 2026-07-17. The build below deliberately supports linux/amd64 only because
# the pinned Pandoc package is architecture-specific.
FROM python:3.13.5-bookworm@sha256:6c6b3c2deae72b980c4323738be824884c9a2e17588c93db82612f8a3072be88

ARG TARGETARCH
ARG R_VERSION=4.5.0
ARG R_SHA256=3b33ea113e0d1ddc9793874d5949cec2c7386f66e4abfb1cef9aec22846c3ce1
ARG PANDOC_VERSION=3.10
ARG PANDOC_SHA256=d502599878eb29af3ae5f0cb5d559134df96534125d452c7a0674a5bad2c5ecf

ENV TZ=UTC \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    OMP_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1 \
    MKL_NUM_THREADS=1 \
    VECLIB_MAXIMUM_THREADS=1 \
    NUMEXPR_NUM_THREADS=1 \
    PYTHONHASHSEED=0 \
    R_LIBS_USER=/opt/hfmd/.r_library \
    UV_LINK_MODE=copy \
    UV_NO_PROGRESS=1

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

RUN test "${TARGETARCH:-amd64}" = "amd64" \
    && apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      build-essential \
      ca-certificates \
      curl \
      fonts-dejavu-core \
      gfortran \
      git \
      libblas-dev \
      libbz2-dev \
      libcairo2-dev \
      libcurl4-openssl-dev \
      libicu-dev \
      libjpeg-dev \
      liblapack-dev \
      liblzma-dev \
      libpcre2-dev \
      libpng-dev \
      libreadline-dev \
      libtiff-dev \
      libtirpc-dev \
      libx11-dev \
      libxml2-dev \
      libxt-dev \
      make \
      perl \
      xz-utils \
      zlib1g-dev \
    && curl -fsSLo /tmp/R.tar.gz \
      "https://cran.r-project.org/src/base/R-4/R-${R_VERSION}.tar.gz" \
    && echo "${R_SHA256}  /tmp/R.tar.gz" | sha256sum --check --strict \
    && mkdir -p /tmp/R-src \
    && tar -xzf /tmp/R.tar.gz -C /tmp/R-src --strip-components=1 \
    && cd /tmp/R-src \
    && ./configure \
      --prefix=/usr/local \
      --enable-R-shlib \
      --with-blas \
      --with-lapack \
      --with-x=no \
    && make -j2 \
    && make install \
    && curl -fsSLo /tmp/pandoc.deb \
      "https://github.com/jgm/pandoc/releases/download/${PANDOC_VERSION}/pandoc-${PANDOC_VERSION}-1-amd64.deb" \
    && echo "${PANDOC_SHA256}  /tmp/pandoc.deb" | sha256sum --check --strict \
    && apt-get install -y --no-install-recommends /tmp/pandoc.deb \
    && rm -rf /tmp/R-src /tmp/R.tar.gz /tmp/pandoc.deb /var/lib/apt/lists/*

RUN python -m pip install --no-cache-dir uv==0.11.29

WORKDIR /opt/hfmd

COPY .gitignore .python-version pyproject.toml uv.lock README.md ./
COPY config ./config
COPY public_repo ./public_repo
COPY Script_r ./Script_r
COPY src ./src
COPY tests ./tests
COPY workflow ./workflow

RUN uv sync --locked --extra analysis --extra workflow --extra dev \
    && mkdir -p "${R_LIBS_USER}" \
    && Rscript -e 'install.packages("https://cloud.r-project.org/src/contrib/Archive/renv/renv_1.2.3.tar.gz", repos = NULL, lib = Sys.getenv("R_LIBS_USER"))' \
    && Rscript -e 'renv::restore(lockfile = "Script_r/renv.lock", library = Sys.getenv("R_LIBS_USER"), prompt = FALSE)' \
    && uv run --locked hfmd config validate --profile synthetic \
    && Rscript Script_r/tests/test_visual_contract.R

# The private repository history is never copied into the image. A clean,
# deterministic source-only commit provides the Git provenance required by
# run manifests without exposing any private history or ignored data.
RUN git init --initial-branch=main \
    && git config user.name "HFMD container builder" \
    && git config user.email "noreply@invalid.example" \
    && git add --all \
    && GIT_AUTHOR_DATE=2000-01-01T00:00:00Z \
       GIT_COMMITTER_DATE=2000-01-01T00:00:00Z \
       git commit -m "Locked container source"

ENTRYPOINT ["uv", "run", "--locked", "hfmd"]
CMD ["--help"]
