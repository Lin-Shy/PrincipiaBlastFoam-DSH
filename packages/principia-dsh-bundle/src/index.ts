/**
 * PrincipiaBlastFoam policy plugin for DeepSeek Harness.
 *
 * The module intentionally uses only the documented `ctx.systemPrompt` surface
 * at runtime. Keeping the compiled plugin dependency-free prevents a second,
 * incompatible Cordis copy from entering an installed DSH profile.
 */

export const name = 'principia-blastfoam-policy'
export const inject = ['systemPrompt'] as const

interface PromptSection {
  readonly name: string
  readonly order: number
  readonly text: string
}

interface SystemPromptService {
  getSectionOrder(name: 'TEAM_POLICY'): number
  section(section: PromptSection): () => void
}

/** The exact service surface consumed by this plugin. */
export interface PrincipiaContext {
  readonly systemPrompt: SystemPromptService
}

export const PRINCIPIA_POLICY = `PrincipiaBlastFoam workflow policy:
- Treat physical analysis, case setup, solver execution, post-processing, and review as ordered phase gates. Do not claim a later phase succeeded when an earlier required phase failed.
- Use the principia_retrieval MCP tools for tutorial, file, variable, and user-guide evidence. Cite the selected case paths and retrieved files in the workflow evidence.
- Keep generated cases and reports inside the active workspace. Never modify OpenFOAM or blastFoam installation sources as part of a case task.
- Preserve the deterministic artifact contract. A completed run must account for physics_report.md, execution_report.md, execution_status.json, post_processing_report.md, review_report.md, workflow_evidence.md, and artifact_contract.json. Mark an unavailable artifact explicitly instead of fabricating it.
- The review phase is independent and read-only. It returns structured review content to the parent; a deterministic writer or the parent materializes review_report.md, workflow_evidence.md, and artifact_contract.json after preserving the reviewer response verbatim.
- Treat successful process exit as necessary but insufficient: verify solver log health, expected time directories, required fields, finite values, and artifact provenance before reporting success.`

/** Register stable, model-visible workflow and artifact requirements. */
export function apply(ctx: PrincipiaContext): void {
  ctx.systemPrompt.section({
    name: 'principia-blastfoam:workflow-policy',
    order: ctx.systemPrompt.getSectionOrder('TEAM_POLICY'),
    text: PRINCIPIA_POLICY,
  })
}
