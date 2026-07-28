def _stage_module(name):
    module_name = STAGE_MODULES.get(name)
    if not module_name:
        return f"hfmd.{name}.pipeline"
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]*", str(module_name)):
        raise ValueError(f"Unsafe stage module for {name}: {module_name!r}")
    return str(module_name)


rule ecological_analysis:
    input:
        DATA_RECEIPT
    output:
        ECOLOGICAL_RECEIPT
    params:
        worker=_stage_module("ecological"),
        run_root=str(RUN_ROOT)
    threads: int(RUNTIME.cores)
    resources:
        mem_mb=int(RUNTIME.memory_gb * 1024 * 0.6)
    shell:
        """
        {EXEC_ENV} {PYTHON_RUNNER} -m {params.worker} \
          --run-id {RUN_ID:q} --profile {PROFILE:q} --run-root {params.run_root:q} \
          --data-receipt {input:q} --receipt {output:q}
        """


rule dynamics_analysis:
    input:
        DATA_RECEIPT
    output:
        DYNAMICS_RECEIPT
    params:
        worker=_stage_module("dynamics"),
        run_root=str(RUN_ROOT)
    threads: int(RUNTIME.cores)
    resources:
        mem_mb=int(RUNTIME.memory_gb * 1024)
    shell:
        """
        {EXEC_ENV} {PYTHON_RUNNER} -m {params.worker} \
          --run-id {RUN_ID:q} --profile {PROFILE:q} --run-root {params.run_root:q} \
          --data-receipt {input:q} --receipt {output:q}
        """
