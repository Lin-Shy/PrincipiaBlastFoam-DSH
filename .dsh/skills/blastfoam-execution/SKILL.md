---
name: blastfoam-execution
description: Run an approved blastFoam/OpenFOAM case with reproducible preflight checks, logs, status classification, and evidence preservation.
---

# blastFoam execution

Use this skill after case setup validation.

## Procedure

1. Record the case path, solver, OpenFOAM/blastFoam environment, command line, and input manifest.
2. Run non-destructive preflight checks: expected files, dictionary parsing when available, executable discovery, disk space, and stale-process/output detection.
3. Execute only the approved case. Preserve stdout/stderr and timing. Do not change physics or dictionaries while the run is in progress.
4. Classify the result using exit status and log evidence. Search for fatal errors, floating-point exceptions, divergence, non-finite values, missing libraries, premature termination, and normal end markers.
5. Check that expected time directories and fields exist before declaring success.

## Outputs

Produce `execution_report.md` and `execution_status.json`. The JSON must include a status, command, exit code, start/end timestamps, log paths, last completed time, detected failure markers, and output evidence. Use `blocked` when the environment is unavailable and `failed` when execution was attempted but invalid.
