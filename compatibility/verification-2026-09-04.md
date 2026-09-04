# Compatibility verification — 2026-09-04

Baseline: upstream DSH commit `d347e703908d0406b7a7ef80e3a0e594d86b2215`, root version `0.1.3-alpha.1`, Node `v24.15.0`, and pnpm `11.7.0`.

Passed checks:

- `npm run check`: TypeScript compilation and Node policy/manifest tests passed.
- `npm pack --dry-run --json`: the tarball contains the bundle patch, compiled ESM entry, declarations, source, and README.
- A disposable Web profile accepted the local bundle, and `--dump-config` composed the policy plugin, MCP client, five distinct role tools, `PRINCIPIA_CASE_ROOT`, and tutorial root without duplicate row IDs.
- A short-lived Web host boot completed. The stdio MCP server answered DSH's `ListToolsRequest` before the Web URL was published.
- A keyless integration check mounted the current DSH `@deepseek-ai/dsh-mcp-client` directly against the project `.venv` (`mcp==1.29.1`), discovered all 17 tools, and completed real `CallToolRequest` calls for `get_status`, non-execution `complete_workflow`, and execution-gated `run_case`.
- The same DSH client preserved MCP schema limits (`top_k <= 20`) and returned tool errors for a case path outside `PRINCIPIA_CASE_ROOT` and `max_lines=1001`; no solver process was started.
- The official `FileSystemSkillProvider` discovered seven entries from this repository as `project-dsh` skills.
- The isolated project virtual environment passed all 38 Python domain/MCP tests, including execution-default, explicit-disable, non-execution fallback, tutorial-routing, portable environment, and invalid bashrc fail-closed regressions, and exposed 17 MCP tools.
- The chapter 3 compatibility adapter selected one case from the existing benchmark in dry-run mode, wrote the legacy `run_*/benchmark_report.json` shape, reported `cases_executed: 0`, and created neither case nor log directories.
- A credential-injected upstream headless smoke returned `DSH_SMOKE_OK`; the credential remained outside Git and was not persisted in the DSH profile.
- A second read-only headless smoke loaded `blastfoam-workflow`, called MCP status and case-intent tools from the parent, and resolved the request to `blastFoam/freeField`.
- Retrieval reported 3,990 case nodes and 5,303 relationships from 28 graph files.
- `blastfoam_physics_analyst` started under its role allowlist, independently called the same two MCP tools, selected the same tutorial, and returned a physics handoff with measurable acceptance criteria.
- Session evidence contained no shell, write, edit, case-initialization, workflow-finalization, or execution calls. No case or solver run was created.
- A separate four-role headless smoke ran in strict order against the ignored workspace fixture `outputs/dsh-role-smoke-freefield`, with `ENABLE_EXECUTION=false` and a case-root boundary at the repository's `outputs` directory.
- `blastfoam_case_setup` called only `initialize_case` and `case_digest`. It selected `blastFoam/freeField`, copied the case inside the bounded output directory, reported 15 dictionaries and no missing core files, and did not call shell or generic file tools.
- `blastfoam_execution_specialist` called only the execution skill, `execution_preflight`, and `run_case`. Preflight passed, but `run_case` returned `started: false`, `blocked: true`, and `ENABLE_EXECUTION is not true; solver was not started.`
- `blastfoam_postprocessor` called only the post-processing skill, `write_post_processing`, and `diagnostics`; it did not use its allowed shell capability. Its deterministic report recorded only initial time `0`, no `postProcessing` directory, and no probe fields.
- `blastfoam_quality_reviewer` called only its allowed `skill`, `read`, `glob`, and `grep` tools (1, 23, 9, and 4 calls respectively). It made no write or shell call and returned a fail-closed review in response text.
- The parent session called the four named role tools plus skills and todo tracking only; it did not call shell, write, or edit. The case tree contained no time directory after `0`, solver log, `processor*`, or `postProcessing` output after the run.
- The role smoke intentionally retained honest negative evidence: the reviewer found that the spherical-charge request did not match the tutorial's box-charge configuration, the then-current generated physics report incorrectly said execution was enabled, and three required final artifacts remained unavailable. The fallback execution-flag defect was subsequently fixed to use the actual `ENABLE_EXECUTION` gate and covered by a Python regression test; the captured ignored smoke fixture predates that fix. The geometry and artifact gaps remain open, so this is not a successful end-to-end workflow claim.
- Solver execution now defaults on in the domain service, MCP schemas, DSH bundle environment, local wrapper, and chapter 3 adapter. `ENABLE_EXECUTION=false` plus `REQUIRE_EXECUTION=false` remains the explicit non-executing override.
- The first real-solver routing smoke exposed a tie that selected `blastFoam/triplePointShockInteration` for a Chinese shock-tube request. Its solver ended cleanly, but the run was rejected as a selection failure rather than counted as validation success.
- Deterministic routing was corrected and covered by a regression test. A fresh isolated MCP-domain smoke then selected `blastFoam/shockTube_tabulated`, ran as the unprivileged `openfoam` user with a 60-second timeout, and completed with return code 0, no timeout, clean solver `End`, and output times `5e-06` and `1e-05`.
- Strict validation of that corrected run passed all physics, execution, post-processing, execution-status, diagnostic, and review checks. Its seven-artifact contract is `ok: true`; one nonblocking `mesh_default_patch` warning remains recorded. Evidence is retained in the ignored runtime case directory `outputs/runtime-smoke-shocktube-fixed.LyyLrQ`.

Not yet claimed:

- A real DSH/OpenFOAM chapter 3 end-to-end benchmark has not run against this implementation; only the non-executing adapter dry-run has passed.
- The earlier spherical-charge role-only fixture still has a tutorial/request geometry mismatch and incomplete artifacts; the corrected shock-tube real-solver fixture passes its strict artifact contract.
- The Web boot was stopped deliberately with SIGINT; the Python FastMCP process printed a cancellation traceback during forced test shutdown.

Npm publication note: the upstream source tree reports `0.1.3-alpha.1` for `@deepseek-ai/dsh-mcp-client` and `@deepseek-ai/dsh-tool-subagent`, but that exact MCP client version was not present on npm during this check. The DSH application runtime already owns these packages, so the bundle references the host copies rather than installing an older duplicate.
