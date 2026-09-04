---
name: blastfoam-workflow
description: Orchestrate an end-to-end blastFoam case from physical analysis through setup, execution, post-processing, and independent quality review.
---

# blastFoam workflow

Use this skill for a complete natural-language blastFoam/OpenFOAM simulation request.

## Phase gates

Run these phases in order. Pass each subagent a self-contained prompt containing the user request, active workspace, prior phase handoff, required outputs, and acceptance criteria.

1. Call `blastfoam_physics_analyst`. Require assumptions, dimensions, material models, boundaries, numerical risks, tutorial evidence, and measurable acceptance criteria in `physics_report.md`.
2. Call `blastfoam_case_setup` only after accepting the physics handoff. Require a workspace-local case, changed-file manifest, syntax/dimension checks, and no production solver run.
3. Call `blastfoam_execution_specialist` only after setup validation. Require exact commands, environment, solver log classification, `execution_report.md`, and `execution_status.json`.
4. Call `blastfoam_postprocessor` only with execution evidence. Require reproducible observables and `post_processing_report.md`.
5. Call `blastfoam_quality_reviewer` after all preceding evidence is stable. The reviewer is read-only and must fail closed. Preserve its response verbatim, then use a deterministic writer or the parent to materialize only `review_report.md`, `workflow_evidence.md`, and `artifact_contract.json`.

Do not run dependent phases concurrently. Independent retrievals within a phase may run concurrently.

## Completion

A successful answer names the case directory and accounts for every required artifact. Distinguish `passed`, `failed`, `blocked`, and `not-applicable`; never infer solver success from process exit alone.
