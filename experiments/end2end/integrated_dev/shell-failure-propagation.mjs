// Opt-in result policy. Never retry a command or infer failure from stderr text.
export const name = 'shell-failure-propagation';
export const inject = ['tools'];

export function failedForeground(exec, result) {
  const value = result.value;
  return exec.name === 'pwsh' && !result.isError && value?.kind === 'foreground' &&
    (value.timedOut === true || value.aborted === true || value.signal != null ||
      value.sandbox?.denied === true || value.sandbox?.runnerFailed === true ||
      (typeof value.exitCode === 'number' && value.exitCode !== 0));
}

export function apply(ctx) {
  ctx.on('tools/post-execute', async (exec, result, next) => {
    if (!failedForeground(exec, result)) return next();
    // The official error result has no typed value; preserve it losslessly in
    // feedback, together with the original rendered output and extra context.
    return {
      kind: 'block',
      feedback: [{type: 'text', text: 'SHELL_EXECUTION_FAILED: shell execution reported failure; command side effects may already exist. No retry was performed.\n' +
        JSON.stringify({originalValue: result.value})}, ...result.content],
      ...(result.additionalContexts ? {additionalContexts: result.additionalContexts} : {}),
    };
  });
}
