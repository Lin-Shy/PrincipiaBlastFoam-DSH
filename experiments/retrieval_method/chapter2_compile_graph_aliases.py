"""Compile source-owned, independently checked aliases; never reads QA data."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path

MODEL = 'deepseek-flash'
ENDPOINT = 'https://api.deepseek.com/chat/completions'


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verified_rows(task, index, folder):
    """Rebuild accepted rows from both bound responses, rather than trust a list."""
    accepted_path = folder/'accepted.json'
    if not accepted_path.exists():
        return [], {'task': index, 'status': 'not_accepted'}
    proposal = read(folder/'propose.json')
    verifier = read(folder/'verify.json')
    accepted = read(accepted_path)
    for record in (proposal, verifier):
        body = record['request']
        fingerprint = hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        if (record['status'] != 'response' or record['model'] != MODEL or record['endpoint'] != ENDPOINT
                or body['model'] != MODEL or record['raw_response']['model'] != MODEL
                or record['request_sha256'] != fingerprint or record['transport_attempts'] != 1):
            raise ValueError('Unbound or non-exact alias review')
        choice = record['raw_response']['choices'][0]
        if choice['finish_reason'] != 'stop' or json.loads(choice['message']['content']) != record['parsed']:
            raise ValueError('Alias response parsing drift')
    if json.loads(proposal['request']['messages'][1]['content']) != task:
        raise ValueError('Proposal source identity changed')
    units = {u['unit_id']: u for u in task['units']}
    candidates = []
    for row in proposal['parsed'].get('aliases', []):
        if (row.get('unit_id') not in units or not isinstance(row.get('quote'), str)
                or not row['quote'].strip() or row['quote'] not in units[row['unit_id']]['text']):
            continue
        aliases = row.get('aliases')
        if not isinstance(aliases, list) or not all(isinstance(v, str) and 1 <= len(v) <= 40 for v in aliases):
            continue
        candidates.append(row)
    if json.loads(verifier['request']['messages'][1]['content']) != dict(source=task, candidate=candidates):
        raise ValueError('Verification source identity changed')
    allowed = {r['unit_id']: r for r in candidates}
    rebuilt = []
    for row in verifier['parsed'].get('verdicts', []):
        uid = row.get('unit_id')
        if uid not in allowed or not isinstance(row.get('accepted_aliases', []), list):
            continue
        aliases = [v for v in row.get('accepted_aliases', []) if v in allowed[uid]['aliases']]
        if aliases:
            rebuilt.append(dict(unit_id=uid, aliases=aliases, quote=allowed[uid]['quote']))
    if (accepted['task'] != index or accepted['path'] != task['path'] or accepted['accepted'] != rebuilt
            or accepted['proposer_sha256'] != sha(folder/'propose.json')
            or accepted['verifier_sha256'] != sha(folder/'verify.json')):
        raise ValueError('Accepted aliases are not bound to their two reviews')
    return rebuilt, dict(task=index, status='accepted', accepted_sha256=sha(accepted_path),
        proposer_sha256=accepted['proposer_sha256'], verifier_sha256=accepted['verifier_sha256'])


def attach(graph, tasks, records):
    """Aliases change the owning raw node only; facts, units and edges stay intact."""
    result = deepcopy(graph)
    raw = {n['unit_id']: n for n in result['nodes'].values() if n['kind'] == 'original_unit'}
    observed = set()
    for task in tasks:
        for row in task['units']:
            uid = row['unit_id']
            if uid in observed:
                raise ValueError('Source unit repeated across alias batches')
            observed.add(uid)
            unit = graph['units'][uid]
            if any(row[k] != unit[k] for k in ('path', 'start', 'end', 'text')):
                raise ValueError('Source task drift')
            if row['path'] != task['path'] or unit['kind'] != 'markdown_section':
                raise ValueError('Alias task is not an owning Markdown source')
    aliases_added = 0
    for row in records:
        uid = row['unit_id']
        if uid not in observed or uid not in raw or row['quote'] not in graph['units'][uid]['text']:
            raise ValueError('Alias lacks its original owned source quote')
        node = raw[uid]
        aliases = list(dict.fromkeys(row['aliases']))[:6]
        new = [a for a in aliases if a not in node.get('aliases', [])]
        node.setdefault('aliases', []).extend(new)
        node.setdefault('alias_grounding', []).append(dict(aliases=aliases, quote=row['quote'],
            path=node['path'], source_sha256=graph['units'][uid]['sha256'],
            status='source_only_AI_proposal_and_independent_AI_review_not_human_truth'))
        aliases_added += len(new)
    return result, dict(aliases_added=aliases_added, source_units_with_aliases=len({r['unit_id'] for r in records}),
        source_units_registered=len(observed))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--graph', type=Path, required=True)
    p.add_argument('--aliases', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    from chapter2_knowledge_input_guard import install
    install()
    protocol = read(a.aliases/'protocol.json')
    if protocol['model'] != MODEL or protocol['gold_or_questions_used'] or sha(a.aliases/'tasks.json') != protocol['tasks_sha256']:
        raise ValueError('Source-only alias protocol drift')
    graph = read(a.graph)
    source_graph_hash = graph.get('literal_heading_revision', {}).get('input_graph_sha256', sha(a.graph))
    if source_graph_hash != protocol['graph_sha256']:
        raise ValueError('Aliases refer to a different original graph')
    tasks = read(a.aliases/'tasks.json')
    if not (a.aliases/('completion-'+str(len(tasks))+'.json')).exists():
        raise ValueError('Alias run must close before graph compilation')
    rows = []; bindings = []
    for index, task in enumerate(tasks):
        accepted, binding = verified_rows(task, index, a.aliases/'sessions'/f'{index:03d}')
        rows.extend(accepted); bindings.append(binding)
    result, counts = attach(graph, tasks, rows)
    result['bilingual_alias_revision'] = dict(schema='source_owned_verified_aliases_v1', model=MODEL,
        input_graph_sha256=sha(a.graph), protocol_sha256=sha(a.aliases/'protocol.json'),
        builder_sha256=sha(Path(__file__)), tasks=bindings, **counts,
        tasks_accepted=sum(b['status']=='accepted' for b in bindings), tasks_registered=len(tasks),
        questions_or_gold_used=False, new_semantic_facts_or_edges=0, original_units_unchanged=True)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    with a.output.open('x', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(json.dumps({k:v for k,v in result['bilingual_alias_revision'].items() if k!='tasks'}))


if __name__ == '__main__':
    main()
