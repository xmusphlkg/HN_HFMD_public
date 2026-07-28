PUBLIC_DESTINATION = config.get("public_export_destination")


rule export_public_repository:
    input:
        data=DATA_RECEIPT,
        submission=SUBMISSION_RECEIPT,
    output:
        PUBLIC_EXPORT_RECEIPT
    params:
        destination=lambda wildcards: (
            str(Path(PUBLIC_DESTINATION).resolve()) if PUBLIC_DESTINATION else ""
        )
    threads: 1
    resources:
        mem_mb=2048
    run:
        if not params.destination:
            raise ValueError(
                "public_export_destination is required and must be outside the private repository"
            )
        shell(f"mkdir -p {shlex.quote(str(RECEIPT_ROOT))}")
        shell(
            f"{EXEC_ENV} {PYTHON_RUNNER} -m hfmd.privacy.pipeline "
            f"--run-id {shlex.quote(RUN_ID)} "
            f"--run-root {shlex.quote(str(RUN_ROOT))} "
            f"--workspace {shlex.quote(str(ROOT))} "
            f"--data-receipt {shlex.quote(str(input.data))} "
            f"--submission-receipt {shlex.quote(str(input.submission))} "
            f"--synthetic-source {shlex.quote(str(SYNTHETIC_ROOT))} "
            f"--destination {shlex.quote(params.destination)} "
            f"--receipt {shlex.quote(str(output[0]))}"
        )
