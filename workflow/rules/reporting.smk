rule render_figures:
    input:
        ecological=ECOLOGICAL_RECEIPT,
        dynamics=DYNAMICS_RECEIPT,
    output:
        FIGURES_RECEIPT
    params:
        worker=STAGE_MODULES.get("figures", "hfmd.reporting.figures"),
        run_root=str(RUN_ROOT)
    threads: 1
    resources:
        mem_mb=int(config.get("figures_mem_mb", 4096))
    shell:
        """
        {EXEC_ENV} {PYTHON_RUNNER} -m {params.worker} \
          --run-id {RUN_ID:q} --profile {PROFILE:q} --run-root {params.run_root:q} \
          --ecological-receipt {input.ecological:q} \
          --dynamics-receipt {input.dynamics:q} --receipt {output:q}
        """


rule build_manuscript:
    input:
        figures=FIGURES_RECEIPT,
        ecological=ECOLOGICAL_RECEIPT,
        dynamics=DYNAMICS_RECEIPT,
    output:
        MANUSCRIPT_RECEIPT
    params:
        worker=STAGE_MODULES.get("manuscript", "hfmd.reporting.manuscript"),
        run_root=str(RUN_ROOT)
    threads: 1
    resources:
        mem_mb=int(config.get("manuscript_mem_mb", 2048))
    shell:
        """
        {EXEC_ENV} {PYTHON_RUNNER} -m {params.worker} \
          --run-id {RUN_ID:q} --profile {PROFILE:q} --run-root {params.run_root:q} \
          --figures-receipt {input.figures:q} --receipt {output:q}
        """


rule build_submission:
    input:
        MANUSCRIPT_RECEIPT
    output:
        SUBMISSION_RECEIPT
    params:
        worker=STAGE_MODULES.get("submission", "hfmd.reporting.submission"),
        run_root=str(RUN_ROOT)
    threads: 1
    resources:
        mem_mb=int(config.get("submission_mem_mb", 2048))
    shell:
        """
        {EXEC_ENV} {PYTHON_RUNNER} -m {params.worker} \
          --run-id {RUN_ID:q} --profile {PROFILE:q} --run-root {params.run_root:q} \
          --journal epidemics --manuscript-receipt {input:q} --receipt {output:q}
        """
