rule environment_preflight:
    output:
        PREFLIGHT_RECEIPT
    params:
        require_r="--require-r" if REQUIRE_R else "",
        require_pandoc="--require-pandoc" if REQUIRE_PANDOC else ""
    threads: 1
    resources:
        mem_mb=256
    shell:
        """
        mkdir -p {RECEIPT_ROOT:q}
        {EXEC_ENV} {PYTHON_RUNNER} -m hfmd.data.preflight \
          --output {output:q} {params.require_r} {params.require_pandoc} \
          --run-id {RUN_ID:q} --run-root {RUN_ROOT:q} --workspace {ROOT:q} \
          --config-snapshot {RUN_ROOT}/config/config.snapshot.json
        """
