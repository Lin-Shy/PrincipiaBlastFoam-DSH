# PrincipiaBlastFoam-DSH contributor instructions

This repository is the independent application source for the DeepSeek Harness implementation of PrincipiaBlastFoam. DeepSeek Harness is an upstream runtime dependency; never implement Principia features inside the upstream checkout.

## Ownership

- `.dsh/skills/`: model-readable blastFoam procedures. Keep skill names kebab-case and one direct `<name>/SKILL.md` entry per skill.
- `packages/principia-dsh-bundle/`: installable DSH bundle, policy plugin, role-specific subagent tool rows, and MCP client row.
- `src/principia_core/`: framework-independent Python domain services.
- `mcp_servers/`: MCP protocol adapters over the domain services.
- `deployment/dsh/`: checked-in templates only. Machine paths, profile state, keys, and credentials stay outside Git.
- `compatibility/`: exact verified DSH commit/package versions and upgrade evidence.

## Invariants

- Preserve DSH bundle/profile separation: `dsh.bundle` belongs to the installable package; DSH creates and owns profile manifests.
- Pin prerelease DSH packages exactly. Do not use `latest`, caret, or unverified ranges.
- A profile patch replaces an entry's complete `config`; restate every required value.
- Reuse the official `spawn` subagent provider. Do not register a second provider with the same process-global name.
- Keep deterministic domain logic and artifact validation outside prompts. Prompts may guide behavior but are not enforcement.
- Never commit credentials or machine-specific absolute paths.
- Keep generated cases, logs, reports, benchmark results, caches, and DSH profile state out of this source tree unless a tracked fixture explicitly requires them.

## Verification

Run the bundle checks, Python tests, a profile `--dump-config`, MCP status smoke test, and the relevant benchmark cases. Any DSH upgrade must update `compatibility/dsh-version.json` only after the acceptance matrix passes.
