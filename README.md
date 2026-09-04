# PrincipiaBlastFoam-DSH

Independent DeepSeek Harness application for natural-language-driven blastFoam/OpenFOAM analysis, case setup, execution, post-processing, and quality review.

This repository owns the application. The upstream DeepSeek Harness checkout is only a replaceable host runtime:

```text
DeepSeek Harness profile
  -> principia-blastfoam-dsh-bundle
     -> workflow policy and role-specific subagent tools
     -> @deepseek-ai/dsh-mcp-client
        -> Python Principia retrieval/domain services
  -> project .dsh/skills
```

## Current implementation

- Seven project skills cover orchestration, retrieval, and the five ordered workflow phases.
- The installable bundle mounts a stable workflow/artifact policy and five role-specialized tools over DSH's official in-process `spawn` provider.
- The bundle connects the independent Python retrieval/domain server through stdio MCP. Its 17 tools appear as `mcp__principia_retrieval__<tool>`.
- Exact upstream compatibility and upgrade gates live under `compatibility/`.

The orchestration sequence is:

```text
physics analysis -> case setup -> execution -> post-processing -> review
```

Dependent phases are not parallel. A phase may parallelize independent evidence collection.

## Quick start

The verified installation in this workspace is deliberately split into three
locations:

```text
<workspace>/deepseek-harness                     replaceable upstream DSH host
<workspace>/dsh-home                              machine-local DSH profiles
<workspace>/graduation-projects/PrincipiaBlastFoam-DSH
                                                  version-controlled application
```

Use the workspace wrapper to start DSH with the project paths and Python
environment already connected:

```bash
cd "$PRINCIPIA_PROJECT_ROOT"
principia-dsh --profile web
```

For a headless task, append the task text after `--profile headless`. The
workspace wrapper reads its locally provisioned API-key file into the child
process only; it does not copy the credential into this repository or the DSH
profile.

The commands below reproduce the project environments if this workspace is
moved to another machine.

Prepare Python:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
pytest
```

Before enabling solver execution, set `OPENFOAM_BASHRC` and
`BLASTFOAM_BASHRC` in the host environment to that machine's actual setup
scripts. They intentionally have no repository default. If the MCP process
already inherits a fully sourced OpenFOAM environment, they may remain empty;
preflight reports that it is relying on the inherited `PATH`. A configured
path that is not a readable file blocks execution. `ENABLE_EXECUTION` remains
`false` in the tracked template.

Prepare the bundle:

```bash
npm --prefix packages/principia-dsh-bundle install
npm --prefix packages/principia-dsh-bundle run check
```

Export `PRINCIPIA_PROJECT_ROOT` and `PRINCIPIA_PYTHON`, install the bundle into a DSH profile, and verify the composed tree before boot. See [deployment/dsh/README.md](deployment/dsh/README.md) for commands and [compatibility/acceptance-matrix.md](compatibility/acceptance-matrix.md) for upgrade gates.

The compatibility adapter for the existing chapter 3 evaluator is documented
in [experiments/end2end/README.md](experiments/end2end/README.md). Its dry-run
mode validates case selection and result shape without starting DSH or a solver;
real solver execution remains an explicit opt-in.

## Repository boundaries

Do not put this code in the upstream DeepSeek Harness checkout and do not store the live DSH profile in Git. Commit bundle source, built release inputs, skills, MCP/domain code, tests, and configuration templates here. Keep credentials and machine-local paths in the external DSH environment/profile.

DeepSeek Harness is currently pre-stable. Treat the commit in `compatibility/dsh-version.json` as a tested baseline, not as an unrestricted compatibility promise.
