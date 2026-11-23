import {pathToFileURL} from 'node:url';
import path from 'node:path';

const {defineTool} = await import(pathToFileURL(path.join(process.env.C3_RUNTIME, 'packages/core/tools/lib/index.js')).href);
export const name = 'measurement-audit';
export const inject = ['tools'];

function numeric(value) {
  if (!Number.isFinite(value)) throw Error('Expected a finite number');
  return value;
}

const flowUnits = new Map([['m3/s', 1], ['L/s', 1000], ['mL/s', 1000000], ['L/min', 60000]]);

function convertRates({values, from, to}) {
  if (!flowUnits.has(from) || !flowUnits.has(to)) throw Error('Unsupported volume flow unit');
  const factor = flowUnits.get(to) / flowUnits.get(from);
  return {unit: to, factor, values: values.map(value => numeric(numeric(value) * factor))};
}

function coverage({window: [lo, hi], intervals}) {
  numeric(lo);
  numeric(hi);
  if (lo > hi) throw Error('Invalid window');
  let union = [];
  const increments = intervals.map(interval => {
    if (interval === null) return 0;
    const [start, end] = interval;
    let a = Math.max(lo, numeric(start));
    let b = Math.min(hi, numeric(end));
    if (a >= b) return 0;
    let increase = b - a;
    const next = [];
    for (const [left, right] of union) {
      if (right < a || b < left) {
        next.push([left, right]);
      } else {
        increase -= Math.max(0, Math.min(right, b) - Math.max(left, a));
        a = Math.min(a, left);
        b = Math.max(b, right);
      }
    }
    union = [...next, [a, b]].sort((x, y) => x[0] - y[0]);
    return increase;
  });
  const covered = union.reduce((sum, [a, b]) => sum + b - a, 0);
  return {union, increments, covered, uncovered: hi - lo - covered};
}

function attemptEvents({job, events, writeEvent, terminalEvents}) {
  if (!Array.isArray(terminalEvents) || !terminalEvents.length) throw Error('Name the terminal event types');
  const selected = events.filter(event => event.job === job);
  if (!selected.length) throw Error('No events for requested job');
  const attempt = selected.reduce((max, event) => Math.max(max, numeric(event.attempt)), -Infinity);
  let terminal = null;
  const seen = new Set();
  const increments = events.map(event => {
    if (event.job !== job || event.attempt !== attempt) return 0;
    if (terminalEvents.includes(event.event)) terminal = event.event;
    if (event.event !== writeEvent) return 0;
    const time = numeric(event.time);
    if (seen.has(time)) return 0;
    seen.add(time);
    return 1;
  });
  return {attempt, terminal, increments, distinct: seen.size};
}

export function apply(ctx) {
  const operations = [
    ['convert_volume_rates', 'Convert signed volume rates. JSON input: {values,from,to}. Units: m3/s, L/s, mL/s, L/min.', convertRates],
    ['interval_coverage', 'Measure a window union and per-input increments. JSON input: {window:[lo,hi],intervals:[[start,end],null,...]}. Pass null for excluded rows.', coverage],
    ['latest_attempt_events', 'Inspect the highest numbered attempt for a job. JSON input: {job,events:[{job,attempt,event,time}],writeEvent,terminalEvents:[...]}. Reports the last matching terminal event in file order.', attemptEvents],
  ];
  for (const [toolName, description, compute] of operations) {
    ctx.tools.register(defineTool({
      name: toolName, description,
      parameters: {input: {type:'string', required:true, description:'JSON object as described above'}},
      output: {schema:{type:'object', additionalProperties:false, properties:{result:{type:'string',required:true}}},render:(_args,value)=>[{type:'text',text:value.result}]},
      async execute({input}) { return {result: JSON.stringify(compute(JSON.parse(input)))}; },
    }));
  }
}

