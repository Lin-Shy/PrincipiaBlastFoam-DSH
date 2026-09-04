---
name: blastfoam-quality-review
description: Independently audit a PrincipiaBlastFoam run for physics, configuration, execution, post-processing, provenance, and artifact completeness.
---

# blastFoam quality review

Use this skill only after the workflow has stopped changing its case and phase reports.

## Read-only audit

Inspect the user request, `physics_report.md`, case dictionaries and modification manifest, solver logs, `execution_report.md`, `execution_status.json`, `post_processing_report.md`, and produced fields. Cross-check claims against primary files rather than copying earlier conclusions.

Evaluate:

- physical-model suitability and assumption traceability;
- tutorial selection and modification provenance;
- dictionary, dimension, boundary, and field consistency;
- solver termination, numerical health, and output completeness;
- post-processing validity, units, sampling, and reproducibility;
- required artifacts and contradictions across reports.

The reviewer must not execute commands or write or modify files. Return structured content for `review_report.md`, `workflow_evidence.md`, and `artifact_contract.json`; a deterministic writer or the parent materializes those files after preserving the reviewer response verbatim.

Use fail-closed status: missing decisive evidence cannot receive a passing verdict. Record each artifact's path, existence, producer phase, evidence, validation result, and reason.
