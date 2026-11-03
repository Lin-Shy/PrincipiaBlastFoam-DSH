"""Continue the frozen JSON matrix on a new, explicitly recorded 8B endpoint.

Old terminal results are reused byte-for-byte. Requests without a terminal
receipt are recorded as unknown failures and never blindly resent.
"""
import argparse
import os
from pathlib import Path
import shutil
import sys
from types import ModuleType
import objective_experiment as base
import objective_json_pilot as pilot
import objective_json_strict as strict
import objective_json_full as prior
from objective_json_resume_guarded import CircuitBreaker, health

OLD = prior.OUT
OUT = base.BASE/'objective_json_v4'
PRIVATE = base.WORK/'.env.supercomputer.json_transition'


def configure_private(base_url):
    if not base_url or not base_url.rstrip('/').endswith('/v1'):
        raise ValueError('Explicit OpenAI-compatible /v1 base URL required')
    if PRIVATE.exists():
        from chapter2_qwen_local import load_model
        if load_model('qwen3-8b', PRIVATE).endpoint != base_url.rstrip('/')+'/chat/completions':
            raise ValueError('Existing transition settings point to a different endpoint')
        return
    source = base.SUPERCOMPUTER_SETTINGS.read_text(encoding='utf-8-sig').splitlines()
    prefix = 'QWEN_LOCAL_8B_BASE_URL='
    hits = [i for i, line in enumerate(source) if line.strip().startswith(prefix)]
    if len(hits) != 1:
        raise ValueError('Expected exactly one existing 8B base URL setting')
    source[hits[0]] = prefix + base_url.rstrip('/')
    PRIVATE.write_text('\n'.join(source)+'\n', encoding='utf8')


def prepare(base_url):
    if (OUT/'manifest.json').exists():
        raise ValueError('Transition batch already exists; never rewrite a frozen manifest')
    prior.use_full()
    old = base.verify()
    qs = base.read(base.DATA/'model/questions.json')
    old_manifest_sha = base.sha(OLD/'manifest.json')
    inventory, unknown, unstarted = [], [], []
    for c in old['configurations']:
        for q in qs:
            source = OLD/'generation'/c['config_id']/q['id']
            result = source/'result.json'
            item = dict(config_id=c['config_id'], id=q['id'])
            if result.exists():
                target = OUT/'generation'/c['config_id']/q['id']/'result.json'
                target.parent.mkdir(parents=True, exist_ok=True)
                try: os.link(result, target)
                except OSError: shutil.copy2(result, target)
                item.update(source_sha256=base.sha(result), source_manifest_sha256=base.read(result)['manifest_sha256'])
                if item['source_manifest_sha256'] != old_manifest_sha:
                    raise ValueError('Old result has unexpected manifest')
                inventory.append(item)
            elif (source/'requests').exists():
                item['request_hashes'] = {str(p.relative_to(source)).replace('\\','/'):base.sha(p)
                    for p in source.rglob('*.json')}
                unknown.append(item)
            else:
                unstarted.append(item)
    if len(inventory)+len(unknown)+len(unstarted)!=old['tasks']:
        raise ValueError('Incomplete task inventory')
    base.save(OUT/'reuse_inventory.json', inventory)
    base.save(OUT/'unknown_inventory.json', unknown)
    base.save(OUT/'unstarted_inventory.json', unstarted)
    configure_private(base_url)
    base.SUPERCOMPUTER_SETTINGS = PRIVATE
    route = base.supercomputer_deployment()
    deployments = dict(old['deployments']); deployments['qwen3_8b'] = route
    bindings = dict(old['bindings'])
    for p in (Path(__file__), Path(strict.__file__), OLD/'manifest.json', OUT/'reuse_inventory.json',
              OUT/'unknown_inventory.json', OUT/'unstarted_inventory.json'):
        bindings[str(p.relative_to(base.WORK)).replace('\\','/')] = base.sha(p)
    old.update(schema='objective_json_endpoint_transition_v1', created=base.now(), deployments=deployments,
               bindings=bindings, parent_manifest_sha256=old_manifest_sha,
               transition='User supplied replacement 8B endpoint; same registered model and original budgets. Existing terminal results retained; unknown requests are zero-scored and not resent.',
               reused_tasks=len(inventory), unknown_tasks=len(unknown), unstarted_tasks=len(unstarted))
    base.save(OUT/'manifest.json', old)
    for item in unknown:
        path = OUT/'generation'/item['config_id']/item['id']/'result.json'
        base.save(path, dict(id=item['id'], config_id=item['config_id'], status='unknown_request_state',
            answer=None, references=None, turns=[], tool_events=[], elapsed_seconds=0,
            manifest_sha256=base.sha(OUT/'manifest.json'), source_unknown=True,
            reason='Prior request was interrupted without a recoverable receipt; not resent.'))
    print('Transition prepared:',len(inventory),'reused;',len(unknown),'unknown;',len(unstarted),'unstarted')


def use_transition():
    base.OUT = OUT
    base.MANIFEST = OUT/'manifest.json'
    base.SUPERCOMPUTER_SETTINGS = PRIVATE
    base.FORMAT = pilot.FORMAT
    base.question_text = pilot.question_text


def run():
    use_transition()
    health()
    previous = base.supercomputer_client
    breaker = CircuitBreaker()
    def guarded(folder):
        client = previous(folder)
        def call(body, turn):
            response = client(body, turn)
            breaker.observe(response)
            return response
        return call
    base.supercomputer_client = guarded
    base.run('qwen3_8b')


def report():
    use_transition()
    adapter = ModuleType('objective_scoring'); adapter.score = strict.score
    sys.modules['objective_scoring'] = adapter
    base.report()


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('command', choices=('prepare','run','report'))
    p.add_argument('--base-url')
    args = p.parse_args()
    if args.command == 'prepare': prepare(args.base_url)
    elif args.command == 'run': run()
    else: report()
