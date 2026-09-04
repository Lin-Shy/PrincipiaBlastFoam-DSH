# DSH profile integration

DeepSeek Harness profiles are machine-local runtime state. Keep the source of truth in this repository and install the bundle into a profile; do not copy Principia code into the DSH checkout.

## Local development

From a shell where `dsh` is installed:

```bash
cd "$PRINCIPIA_PROJECT_ROOT"
npm --prefix packages/principia-dsh-bundle run check
dsh plugin --profile web add ./packages/principia-dsh-bundle
dsh --profile web --dump-config
dsh --profile web
```

When running DSH from an upstream source checkout, replace `dsh` with `corepack pnpm@11.7.0 --dir "$DSH_CHECKOUT" dsh` where appropriate. Start sessions with the Principia repository as their workspace so `.dsh/skills` is the highest-priority project skill root.

## Stable installation

Build a tested tarball and keep it with the release or CI artifact:

```bash
npm --prefix packages/principia-dsh-bundle pack
dsh plugin --profile web add ./packages/principia-dsh-bundle/principia-blastfoam-dsh-bundle-0.1.0.tgz
```

The tarball contains checked-in JavaScript and requires no install-time build permission. For an npm release, install the exact version rather than a floating tag. For a Git dependency, pin a commit SHA and remember that pnpm requires explicit authorization before running a dependency's `prepare` script; this package avoids that script deliberately.

## Machine-local configuration

Set these variables outside Git:

- `PRINCIPIA_PROJECT_ROOT`: repository root; otherwise DSH uses its launch directory.
- `PRINCIPIA_PYTHON`: interpreter from the Python environment containing this project and `mcp`; otherwise `python3` is used.
- `PRINCIPIA_CASE_ROOT`: only directory in which case-mutating domain tools may operate; defaults to `outputs` under `PRINCIPIA_PROJECT_ROOT`.
- `BLASTFOAM_TUTORIALS`: external blastFoam tutorial root used by retrieval; defaults to a sibling `blastFoam_tutorials` directory.
- `PRINCIPIA_KNOWLEDGE_GRAPH`: optional knowledge-graph file override.
- `RETRIEVAL_LLM_API_KEY`: optional retrieval-fallback credential; the MCP client must pass it explicitly because secret-like ambient names are scrubbed from stdio children.
- `DSH_PERMISSION_MODE`: normally `workspace-write`; never place production secrets in the profile patch.

The bundle MCP row is fail-open by default so DSH can boot while the Python environment is being prepared. Copy the example patch into the profile and keep `failOnStartupError: true` for evaluated or production runs.

After any DSH upgrade, create a temporary profile, install this exact bundle version, run `--dump-config`, check that the MCP tools are present, and execute the compatibility matrix before promoting the version.
