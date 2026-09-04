---
name: blastfoam-physics-analysis
description: Analyze explosion physics and choose a defensible blastFoam tutorial before any case files are created or changed.
---

# blastFoam physics analysis

Use this skill at the start of a new simulation or whenever the physical model changes materially.

## Procedure

1. Normalize the request into geometry, dimensionality, materials, explosive/source specification, initial state, boundaries, requested observables, and time/length scales.
2. Retrieve the MCP server status with `mcp__principia_retrieval__get_status`.
3. Find candidate tutorials with `mcp__principia_retrieval__get_case_by_intent`; inspect relevant files and user-guide evidence before selecting one.
4. State which physical and numerical features transfer unchanged and which require modification.
5. Define stability risks, expected qualitative behavior, quantitative checks, and evidence that would invalidate the proposed setup.

## Output

Write or return a `physics_report.md` handoff containing the selected tutorial path, retrieval evidence, assumptions, equations/models, boundary and initial conditions, numerical plan, unresolved questions, and acceptance criteria. Do not edit a case or execute the solver in this phase.
