# DSH compatibility acceptance matrix

Do not update the supported DSH commit from a version number alone. DSH is pre-stable and its package versions can move independently.

| Check | Required evidence | Promotion gate |
|---|---|---|
| Bundle package | `npm run check` and `npm pack --dry-run` pass | Required |
| Profile composition | `dsh --profile <test-profile> --dump-config` includes policy, MCP, and five role tools without duplicate IDs | Required |
| MCP startup | `mcp__principia_retrieval__get_status` returns graph and tutorial status | Required |
| Skill discovery | all seven project skills appear from `.dsh/skills` when session cwd is the repository | Required |
| Role isolation | physics analyst and reviewer cannot call shell or write/edit tools; reviewer returns review content without materializing it | Required |
| Artifact contract | a smoke case accounts for all seven required artifacts and reviewer does not modify protected inputs | Required |
| Regression | selected smoke cases and the full chapter 3 benchmark preserve expected statuses | Required before release |

Test upgrades in a disposable profile while the previously verified profile remains available. Update `dsh-version.json` only after the required checks pass; record known failures instead of widening a version range speculatively.
