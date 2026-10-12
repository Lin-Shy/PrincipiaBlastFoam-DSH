"""按章节批量调用官方 DeepSeek，冻结模型与请求并校验关系出处。"""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
import fcntl
import json
from pathlib import Path
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import manual_graph as g
from global_graph import locate_quote

ENDPOINT = 'https://api.deepseek.com/chat/completions'
RELATIONS = {'DEFINES_PARAMETER', 'SELECTED_BY', 'REQUIRES_INPUT', 'COMPATIBLE_WITH',
             'LIMITED_TO', 'HAS_CONDITION', 'USES_MODEL', 'INITIALIZED_BY', 'DESCRIBES', 'REFERENCES'}
KINDS = {'model', 'parameter', 'file', 'solver', 'utility', 'concept'}
PROMPT = g.ROOT/'references/manual-semantic-prompt.md'
MODELS = ('deepseek-flash',)


def make_plan(graph, chapter='05_fluid_solid_thermo.md', batch_characters=6500, prompt_path=PROMPT,
              model='deepseek-flash', global_catalog=False):
    if model not in MODELS:
        raise ValueError('unsupported extraction model')
    byid = {n['id']: n for n in graph['nodes']}
    sections = [n for n in graph['nodes'] if n['kind'] == 'section']
    targets = [s for s in sections if s['path'] == chapter]
    if not targets:
        raise ValueError('chapter not found')
    scope_ids = {s['id'] for s in targets}
    scope_ids.update(e['target'] for e in graph['edges'] if e['relation'] == 'REFERS_TO_SECTION'
                     and byid[e['source']].get('section') in scope_ids)
    if global_catalog:
        scope_ids.update(s['id'] for s in sections if not s['path'].startswith('00_'))
    catalog = [{k: s[k] for k in ('id', 'label')} for s in sections if s['id'] in scope_ids]
    batches = []; batch = []; size = 0
    for s in targets:
        length = len(s['heading_markdown']) + sum(len(byid[u]['markdown']) for u in s['units'])
        if batch and (size+length > batch_characters or len(batch) >= 6):
            batches.append(batch); batch = []; size = 0
        batch.append(s); size += length
    if batch:
        batches.append(batch)
    prompt = Path(prompt_path).read_text()
    plan = {'schema': 'manual-semantic-plan-v1', 'foundation_snapshot': graph['snapshot'],
            'chapter': chapter, 'prompt': prompt, 'catalog': catalog,
            'extraction': {'model': model, 'temperature': 0, 'thinking': {'type': 'disabled'},
                           'max_tokens': 12000, 'response_format': {'type': 'json_object'}}, 'batches': []}
    for i, batch in enumerate(batches, 1):
        active = {s['id'] for s in batch}; context = set()
        for s in batch:
            parent = s['parent']
            while byid[parent]['kind'] == 'section':
                context.add(parent); parent = byid[parent]['parent']
        for e in graph['edges']:
            if e['relation'] == 'REFERS_TO_SECTION' and byid[e['source']].get('section') in active:
                context.add(e['target'])
        sources = []
        for s in sections:
            if s['id'] not in active | context:
                continue
            for node in [s, *[byid[u] for u in s['units']]]:
                text = node.get('markdown', node.get('heading_markdown'))
                sources.append({'id': node['id'], 'section': s['id'], 'path': s['path'],
                                'line_start': node['start'], 'sha256': s['sha256'], 'pdf_page': None,
                                'text': text, 'target': s['id'] in active})
        unit = {'id': f'batch-{i:03}', 'target_sections': [s['id'] for s in batch], 'sources': sources}
        unit['cache_key'] = g.sha(g.encoded({'unit': unit, 'prompt': prompt,
                                           'catalog': catalog, 'extraction': plan['extraction']}))
        plan['batches'].append(unit)
    plan['snapshot'] = g.sha(g.encoded(plan))
    return plan


def request_body(plan, unit):
    return {**plan['extraction'], 'messages': [
        {'role': 'system', 'content': plan['prompt']},
        {'role': 'user', 'content': g.encoded({'catalog': plan['catalog'],
           'target_sections': unit['target_sections'], 'sources': unit['sources']})}]}


def invoke(body, key, retries=3, timeout=240):
    """有效 HTTP 响应先原样保存；格式/语义问题不重新采样。"""
    events = []
    for attempt in range(1, retries+1):
        start = time.monotonic()
        try:
            req = Request(ENDPOINT, data=json.dumps(body).encode(),
                          headers={'Authorization': 'Bearer '+key, 'Content-Type': 'application/json'})
            with urlopen(req, timeout=timeout) as response:
                raw = response.read().decode('utf-8')
            events.append({'attempt': attempt, 'status': 'response', 'seconds': time.monotonic()-start})
            try:
                data = json.loads(raw)
                return {'status': 'response', 'raw_response': data, 'events': events,
                        'request_sha256': g.sha(g.encoded(body))}
            except ValueError:
                return {'status': 'invalid_response', 'raw_text': raw, 'events': events,
                        'request_sha256': g.sha(g.encoded(body))}
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            events.append({'attempt': attempt, 'status': 'transport_error', 'type': type(exc).__name__,
                           'http_status': getattr(exc, 'code', None), 'seconds': time.monotonic()-start})
            if getattr(exc, 'code', None) in (400, 401, 402, 403):
                break
            if attempt < retries:
                time.sleep(min(attempt*2, 6))
    return {'status': 'transport_error', 'events': events, 'request_sha256': g.sha(g.encoded(body))}


def validate_payload(plan, unit, response):
    data = response['raw_response']
    if data.get('model') != plan['extraction']['model']:
        raise ValueError('response model mismatch')
    choice = data['choices'][0]
    if choice.get('finish_reason') != 'stop':
        raise ValueError('incomplete extraction')
    payload = json.loads(choice['message']['content'])
    if not isinstance(payload, dict) or not isinstance(payload.get('sections'), list):
        raise ValueError('invalid sections payload')
    ids = [s.get('id') for s in payload['sections']]
    if len(ids) != len(set(ids)) or set(ids) != set(unit['target_sections']):
        raise ValueError('target section coverage mismatch')
    sources = {s['id']: s for s in unit['sources']}
    scopes = {s['id'] for s in plan['catalog']}
    accepted = []; rejected = []; coverage = []
    for section in payload['sections']:
        sid = section['id']; count = 0
        if not isinstance(section.get('facts'), list) or not isinstance(section.get('deferred'), list) or not isinstance(section.get('summary_zh'), str):
            raise ValueError('invalid section record')
        for ordinal, fact in enumerate(section['facts']):
            try:
                if fact.get('relation') not in RELATIONS:
                    raise ValueError('invalid relation')
                if not all(isinstance(fact.get(k), str) for k in ('summary_zh', 'conditions_zh')):
                    raise ValueError('missing relation interpretation')
                anchors = fact['anchors']
                if not isinstance(anchors, list) or not anchors:
                    raise ValueError('missing anchors')
                evidence = []; targeted = False
                for anchor in anchors:
                    source = sources[anchor['source']]
                    ev = locate_quote(source, anchor['quote'])
                    ev['source'] = source['id']; evidence.append(ev)
                    targeted |= source['target'] and source['section'] == sid
                if not targeted:
                    raise ValueError('no anchor in current target section')
                entities = []
                for role in ('subject', 'object'):
                    entity = fact[role]
                    if entity.get('kind') not in KINDS or entity.get('scope') not in scopes:
                        raise ValueError('invalid entity kind/scope')
                    name = entity.get('name')
                    if not isinstance(name, str) or not name.strip():
                        raise ValueError('empty entity name')
                    if not any(name in s['text'] for s in unit['sources']):
                        raise ValueError('entity name absent from supplied text: '+name)
                    entity = {k: entity[k] for k in ('name', 'kind', 'scope')}
                    entity['id'] = 'entity:' + g.sha(g.encoded(entity))[:24]
                    entities.append(entity)
                item = {'section': sid, 'subject': entities[0], 'object': entities[1],
                        'relation': fact['relation'], 'summary_zh': fact['summary_zh'],
                        'conditions_zh': fact['conditions_zh'], 'evidence': evidence,
                        'review': 'source_checked_semantic_unreviewed'}
                item['id'] = 'fact:' + g.sha(g.encoded(item))[:24]
                accepted.append(item); count += 1
            except (ValueError, KeyError, TypeError) as exc:
                rejected.append({'section': sid, 'ordinal': ordinal, 'reason': str(exc), 'candidate': fact})
        coverage.append({'section': sid, 'accepted': count, 'proposed': len(section['facts']),
                         'summary_zh': section['summary_zh'], 'deferred': section['deferred']})
    return accepted, rejected, coverage


def assemble(plan, run_dir, graph):
    if plan['foundation_snapshot'] != graph['snapshot']:
        raise ValueError('foundation snapshot mismatch')
    facts = []; rejected = []; coverage = []; usage = Counter(); failures = []
    for unit in plan['batches']:
        path = run_dir/'responses'/f"{unit['id']}.json"
        if not path.exists():
            failures.append({'batch': unit['id'], 'reason': 'missing response'}); continue
        response = json.loads(path.read_text())
        try:
            if response['cache_key'] != unit['cache_key'] or response['request_sha256'] != g.sha(g.encoded(request_body(plan, unit))):
                raise ValueError('request identity mismatch')
            raw = response.get('raw_response', {})
            usage.update({k: v for k, v in raw.get('usage', {}).items() if type(v) is int})
            a, r, c = validate_payload(plan, unit, response)
            facts.extend(a); rejected.extend(r); coverage.extend(c)
        except (ValueError, KeyError, TypeError, IndexError) as exc:
            failures.append({'batch': unit['id'], 'reason': str(exc)})
    entities = {e['id']: e for f in facts for e in (f['subject'], f['object'])}
    semantic = {'schema': 'manual-semantic-v1', 'foundation_snapshot': graph['snapshot'],
                'plan_snapshot': plan['snapshot'], 'facts': facts, 'entities': list(entities.values()),
                'coverage': coverage, 'rejected': rejected, 'failures': failures, 'usage': dict(usage),
                'status': 'partial' if failures else 'source_checked_semantic_unreviewed',
                'limits': ['引句可定位不证明语义正确', '实体按类别、原文名和章节作用域区分', '抽取范围由冻结plan的chapter和target_sections确定']}
    semantic['snapshot'] = g.sha(g.encoded(semantic))
    g.write(run_dir/'semantic.json', semantic)
    return semantic


def run(args):
    graph = json.loads(args.foundation.read_text())
    g.validate(graph, args.source)
    args.run_dir.mkdir(parents=True, exist_ok=True)
    proposed = make_plan(graph, args.chapter, prompt_path=args.prompt, model=args.model, global_catalog=args.global_catalog)
    plan_path = args.run_dir/'plan.json'
    if plan_path.exists():
        plan = json.loads(plan_path.read_text())
        if plan != proposed:
            raise ValueError('plan changed; use a new run directory')
    else:
        plan = proposed; g.write(plan_path, plan)
    print(g.encoded({'batches': len(plan['batches']), 'sections': sum(len(u['target_sections']) for u in plan['batches']),
                     'input_characters': sum(len(g.encoded(request_body(plan, u))) for u in plan['batches'])}), flush=True)
    if args.command == 'prepare':
        return
    if args.command == 'extract':
        if not args.key_file:
            raise ValueError('--key-file required')
        key = args.key_file.read_text().strip()
        if not key or any(c.isspace() for c in key):
            raise ValueError('bare API key required')
        pending = []
        for unit in plan['batches']:
            path = args.run_dir/'responses'/f"{unit['id']}.json"
            if not path.exists() or json.loads(path.read_text()).get('status') == 'transport_error':
                pending.append(unit)
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            jobs = {pool.submit(invoke, request_body(plan, u), key): u for u in pending}
            for future in as_completed(jobs):
                unit = jobs[future]; result = future.result()
                path = args.run_dir/'responses'/f"{unit['id']}.json"
                if path.exists():
                    old = json.loads(path.read_text())
                    result['previous_transport_attempts'] = [*old.get('previous_transport_attempts', []), old['events']]
                result.update({'cache_key': unit['cache_key'], 'unit': unit['id']})
                g.write(path, result)
                print(unit['id'], result['status'], flush=True)
    g.validate(graph, args.source)
    semantic = assemble(plan, args.run_dir, graph)
    print(g.encoded({'facts': len(semantic['facts']), 'entities': len(semantic['entities']),
                     'rejected': len(semantic['rejected']), 'failures': semantic['failures'], 'usage': semantic['usage']}), flush=True)
    if semantic['failures']:
        raise RuntimeError('partial extraction; inspect saved responses')


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=['prepare', 'extract', 'assemble'])
    p.add_argument('--foundation', type=Path, required=True)
    p.add_argument('--source', type=Path, default=g.ROOT/'corpus/manual/markdown')
    p.add_argument('--chapter', default='05_fluid_solid_thermo.md')
    p.add_argument('--model', choices=MODELS, default='deepseek-flash')
    p.add_argument('--global-catalog', action='store_true', help='提供全书章节ID供明示实体跨章定位；不提供答案或题目')
    p.add_argument('--prompt', type=Path, default=PROMPT)
    p.add_argument('--run-dir', type=Path, required=True)
    p.add_argument('--key-file', type=Path)
    p.add_argument('--workers', type=int, choices=range(1, 5), default=4)
    args = p.parse_args()
    args.run_dir.mkdir(parents=True, exist_ok=True)
    with (args.run_dir/'build.lock').open('a') as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        run(args)
