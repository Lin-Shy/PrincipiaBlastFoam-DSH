---
name: blastfoam-case-setup
description: Construct or modify a workspace-local blastFoam case from an approved physics handoff and retrieved tutorial evidence.
---

# blastFoam case setup

Use this skill only after the physics analysis identifies a suitable tutorial and explicit changes.

## Procedure

1. Confirm the source tutorial using `mcp__principia_retrieval__get_files_for_case`.
2. Use `mcp__principia_retrieval__get_modification_targets` and `mcp__principia_retrieval__find_variable` to identify exact dictionaries and entries. Retrieve content before editing.
3. Copy the tutorial into a new workspace-local case. Never edit the tutorial or OpenFOAM/blastFoam installation in place.
4. Apply the smallest coherent changes and record old value, new value, units/dimensions, reason, and source for each change.
5. Validate required dictionaries, dimensions, paths, boundary/field consistency, mesh configuration, time controls, write controls, and runnable scripts.

## Handoff

Return the case path, source tutorial, changed-file manifest, checks performed, warnings, and exact command recommended for execution. Do not run the production solver during setup.
