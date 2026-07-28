if PROFILE in {"ci", "synthetic"}:
    SYNTHETIC_ROOT = RUN_ROOT / "data" / "synthetic"
    SYNTHETIC_MANIFEST = str(SYNTHETIC_ROOT / "synthetic_manifest.json")

    rule build_synthetic_data:
        input:
            PREFLIGHT_RECEIPT
        output:
            SYNTHETIC_MANIFEST
        params:
            root=str(SYNTHETIC_ROOT)
        threads: 1
        resources:
            mem_mb=1024
        shell:
            """
            {EXEC_ENV} {PYTHON_RUNNER} -m hfmd.data.synthetic \
              --profile {PROFILE} --seed {SEED} --output {params.root:q} --replace
            """

    rule register_synthetic_data:
        input:
            SYNTHETIC_MANIFEST
        output:
            DATA_RECEIPT
        params:
            root=str(SYNTHETIC_ROOT)
        threads: 1
        resources:
            mem_mb=512
        shell:
            """
            mkdir -p {RECEIPT_ROOT:q}
            {EXEC_ENV} {PYTHON_RUNNER} -m hfmd.data.pipeline \
              --profile {PROFILE:q} --run-id {RUN_ID:q} --run-root {RUN_ROOT:q} \
              --workspace {ROOT:q} --data-root {params.root:q} \
              --environment-receipt {PREFLIGHT_RECEIPT:q} --receipt {output:q}
            """

    rule audit_synthetic_for_public_use:
        input:
            DATA_RECEIPT
        output:
            PRIVACY_RECEIPT
        params:
            root=str(SYNTHETIC_ROOT)
        threads: 1
        resources:
            mem_mb=512
        shell:
            """
            {EXEC_ENV} {PYTHON_RUNNER} -m hfmd.privacy.audit \
              --root {params.root:q} --classification synthetic --license CC0-1.0 \
              --minimum-cell 10 --report {output:q}
            """

else:
    RESTRICTED_SUCCESS = str(ROOT / "AnalysisData" / "_SUCCESS.json")
    RESTRICTED_OUTPUT_MANIFEST = str(
        ROOT / "AnalysisData" / "audit" / "output_file_manifest.csv"
    )
    RESTRICTED_DELETION_RECEIPT = str(
        ROOT / "AnalysisData" / "audit" / "deletion_receipt.json"
    )

    rule register_restricted_data:
        input:
            preflight=PREFLIGHT_RECEIPT,
            success=RESTRICTED_SUCCESS,
            manifest=RESTRICTED_OUTPUT_MANIFEST,
            deletion=RESTRICTED_DELETION_RECEIPT,
        output:
            DATA_RECEIPT
        threads: 1
        resources:
            mem_mb=1024
        shell:
            """
            mkdir -p {RECEIPT_ROOT:q}
            {EXEC_ENV} {PYTHON_RUNNER} -m hfmd.data.pipeline \
              --profile restricted --run-id {RUN_ID:q} --run-root {RUN_ROOT:q} \
              --workspace {ROOT:q} --data-root {ROOT}/AnalysisData \
              --environment-receipt {PREFLIGHT_RECEIPT:q} --receipt {output:q}
            """
