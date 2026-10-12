// Experimental continuation driver; production headless entry remains unchanged.
import { createRequire } from 'node:module';
import path from 'node:path';
export const name = 'principia-evaluation-resume';
export const inject = ['agents', 'sessions', 'agentDefaultModel'];
export function apply(ctx, config) {
  const exit = ctx.get('appExit');
  if (!exit) throw new Error('launcher appExit is required');
  const run = async () => {
    process.stderr.write('resume_driver: importing\n');
    const moduleRoot = process.env.PRINCIPIA_DSH_MODULE_ROOT;
    if (!moduleRoot || !path.isAbsolute(moduleRoot)) throw new Error('absolute PRINCIPIA_DSH_MODULE_ROOT required');
    const require = createRequire(path.join(moduleRoot, 'evaluation-driver.cjs'));
    const { installModelSelection } = await import(require.resolve('@deepseek-ai/dsh-agent'));
    const { createUserMessage } = await import(require.resolve('@deepseek-ai/dsh-llm'));
    process.stderr.write('resume_driver: awaiting_loader\n');
    await ctx.get('loader')?.await();
    process.stderr.write('resume_driver: restoring_session\n');
    if (config.dryRun) { exit(0); return; }
    const selection = ctx.get('agentDefaultModel').currentSelection();
    const { agent } = await ctx.get('agents').resume({
      resumeSessionId: config.sessionId,
      agentOptions: { provider: selection.provider, model: selection.model },
      setup: agentCtx => { installModelSelection(agentCtx, { current: selection, assembled: undefined }); },
    });
    process.stderr.write('resume_driver: restored\n');
    const firstSeq = agent.session.seq;
    agent.followup(createUserMessage({ content: [{ type: 'text', text: config.task }], source: { kind: 'user' } }));
    process.stderr.write('resume_driver: followup_submitted\n');
    await agent.whenIdle();
    const sessions = ctx.get('sessions');
    if (!sessions) return; // Outer timeout may already be disposing the app.
    await sessions.flush(agent.session);
    const ends = [];
    for (let seq = firstSeq; seq < agent.session.seq; seq++) {
      const event = agent.session.eventAt(seq);
      if (event?.type === 'turn/end') ends.push(event.data.reason);
    }
    process.stdout.write(JSON.stringify({ sessionId: config.sessionId, firstSeq, finalSeq: agent.session.seq, ends }) + '\n');
    exit(ends.at(-1)?.kind === 'completed' ? 0 : 1);
  };
  void run().catch(error => { process.stderr.write(String(error) + '\n'); exit(1); });
}
