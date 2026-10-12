// Optional local DSH adapter. No upstream changes or prompt rewriting.
export const name = 'principia-request-context';
export const inject = ['agents', 'tools'];
const TOOL = 'mcp__principia_retrieval__locate_case_edits';

export function latestUserRequest(events) {
  const event = [...events].reverse().find(e => e.type === 'user/message' && e.data?.source?.kind === 'user');
  if (!event) return '';
  const text = (event.data.content ?? []).filter(p => p.type === 'text' && typeof p.text === 'string').map(p => p.text).join('\n');
  return text.trim() && text.length <= 32768 ? text : '';
}

export function apply(ctx, config = {}) {
  ctx.on('agent/created', ({ agent }) => {
    const names = config.fileNavigation ? [TOOL, 'mcp__principia_retrieval__get_files_for_case'] : [TOOL];
    for (const toolName of names) {
    const original = ctx.tools.get(toolName);
    if (!original) throw new Error('request-context adapter requires the locator MCP tool before agent creation');
    const parameters = structuredClone(original.parameters);
    delete parameters.properties?.original_request;
    if (parameters.required) parameters.required = parameters.required.filter(k => k !== 'original_request');
    agent.ctx.tools.register({
      ...original, parameters,
      description: original.description + (toolName === TOOL ? '\n如有当前用户原始请求，将直接据此定位；query 留作意图记录，不替换原文约束。' : '\n当原始任务明确指向本案例时，同时返回有来源的修改导航；文件列表保持完整。'),
      async execute(args, exec) {
        const request = latestUserRequest(exec.agent?.session.snapshotEvents() ?? []);
        // This scoped tool's adapter prepares MCP service input. It does not
        // mutate the immutable model call identity or its logged arguments.
        return original.execute({ ...args, original_request: request }, exec);
      },
    });
    }
  });
}
