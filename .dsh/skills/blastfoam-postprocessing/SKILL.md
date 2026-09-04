---
name: blastfoam-postprocessing
description: Validate blastFoam result fields and compute reproducible observables without altering the approved case configuration.
---

# blastFoam post-processing

Use this skill after execution evidence is available, including for diagnosing incomplete or failed runs.

## Procedure

1. Read `execution_status.json`, the solver log, and available time directories; do not assume the latest directory is valid.
2. Verify required fields, dimensions, sample locations, finite values, and temporal coverage for every requested observable.
3. Run reproducible OpenFOAM utilities or analysis commands. Record commands, inputs, selections, units, and output paths.
4. Separate physical zero from missing, invalid, truncated, or unevaluated data.
5. Compare results with the physics acceptance criteria and flag discrepancies without rewriting the setup.

## Output

Produce `post_processing_report.md` with provenance, validity checks, derived metrics, figures/tables when requested, limitations, and a clear `passed`, `failed`, `blocked`, or `partial` conclusion.
