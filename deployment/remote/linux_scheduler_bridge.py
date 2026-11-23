"""Linux controller adapter: scheduler-only execution and cluster-resident bulk results.

The operator supplies a separately authorized SSH identity. This module never
copies credentials, accepts model-generated shell payloads, or downloads results.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import shlex


def load_core(path):
    spec = importlib.util.spec_from_file_location('chapter3_scheduler_core', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def guarded_plan(core, config, run_id):
    result = core.plan(config, run_id)
    old = '''scontrol show job "$SLURM_JOB_ID" >/dev/null
node=$(hostname -s)
scontrol show hostnames "$SLURM_JOB_NODELIST" | sed 's/\\..*//' | grep -Fx "$node" >/dev/null'''
    new = '''record=$(scontrol show job -o "$SLURM_JOB_ID")
test "$(printf '%s\\n' "$record" | grep -oE '(^| )JobState=[^ ]+' | cut -d= -f2)" = RUNNING
nodes=$(printf '%s\\n' "$record" | grep -oE '(^| )NodeList=[^ ]+' | cut -d= -f2)
test -n "$nodes" && test "$nodes" = "$SLURM_JOB_NODELIST"
owner=$(printf '%s\\n' "$record" | grep -oE '(^| )UserId=[^ ]+' | sed -E 's/.*\\(([0-9]+)\\)/\\1/')
test "$owner" = "$(id -u)"
node=$(hostname -s)
scontrol show hostnames "$nodes" | sed 's/\\..*//' | grep -Fx "$node" >/dev/null'''
    assert old in result['batch_script']
    result['batch_script'] = result['batch_script'].replace(old, new)
    result['storage_policy'] = 'Bulk inputs and simulation outputs stay on the supercomputer. Windows may retrieve them directly. Linux stores only configuration and bounded control receipts.'
    result['validation'] = 'Offline template only; credential binding and authorized real scheduler acceptance remain required.'
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['plan', 'status', 'results-location'])
    parser.add_argument('--core', type=Path, required=True)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--grant', type=Path)
    parser.add_argument('--receipt', type=Path)
    args = parser.parse_args()
    core = load_core(args.core)
    config = json.loads(args.config.read_text())
    result = guarded_plan(core, config, args.run_id)
    if args.action == 'plan':
        print(json.dumps(result, indent=2))
        return
    if not config.get('live_enabled'):
        raise PermissionError('Live scheduler adapter is disabled until independent credential binding and acceptance')
    grant = json.loads(args.grant.read_text()) if args.grant else {}
    core.authorize(config, grant, args.run_id, args.action)
    receipt = json.loads(args.receipt.read_text()) if args.receipt else {}
    job = str(receipt.get('job_id', ''))
    if receipt.get('run_id') != args.run_id or receipt.get('remote') != result['remote'] or not job.isdigit():
        raise PermissionError('Owned job receipt required')
    if args.action == 'status':
        response = core.ssh(config, 'scontrol show job ' + job, capture_output=True, text=True, timeout=30)
        print(json.dumps({'job_id': job, 'scheduler_text': response.stdout[:16384]}))
    else:
        print(json.dumps({'job_id': job, 'remote_directory': result['remote'],
                          'transfer_policy': 'Retrieve directly from the supercomputer to Windows; no simulation result copy on Linux.'}))


if __name__ == '__main__':
    main()
