---
name: blastfoam-retrieval
description: Retrieve blastFoam tutorial, dictionary, variable, and user-guide evidence through the Principia MCP server with traceable two-stage lookups.
---

# blastFoam retrieval

Use this skill whenever a workflow decision depends on a blastFoam tutorial, dictionary entry, variable, or user-guide claim.

## Procedure

1. Call `mcp__principia_retrieval__get_status` before relying on the knowledge graph.
2. Use narrow deterministic tools first: `get_case_by_intent`, `get_files_for_case`, and `find_variable`.
3. For content search, request candidates first through `search_case_content` or `search_user_guide`; then request detail for a selected `result_id`. Avoid loading large unrelated files.
4. Use `get_file_content` for a known file and `get_modification_targets` for a concrete requested change.
5. Preserve the tool name, query, selected result id, case/file path, and the decision supported by the result in `workflow_evidence.md`.

If the MCP server is unavailable or returns incomplete evidence, report the limitation and do not invent tutorial paths, dictionary values, or documentation claims.
