"""Build a source-backed configuration graph and return bounded original evidence.

No API calls, question IDs, gold annotations, or execution of OpenFOAM directives.
The legacy indexes remain immutable inputs. Derived indexes may be stored externally.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
import re

import knowledge as k

VERSION = 'evidence-bundle-v1'
ROOT = Path(__file__).resolve().parents[1]
ROLE_TERMS = {
    'geometry': r'几何|建筑|障碍|二维|三维|网格|拐角|薄板|\b(geometry|building|obstacle|mesh|corner|plate|2d|3d)\b',
    'initialization': r'初始|起爆|装药|隔膜|左右|点火|\b(initial\w*|ignit\w*|charge|diaphragm)\b',
    'boundary': r'边界|封闭|封住|敞开|入口|出口|两端|\b(boundary|closed|open|inlet|outlet|wall)\b',
    'model': r'材料|物性|表格|反应|颗粒|耦合|燃烧|变形|\b(material|thermo\w*|tabulat\w*|reaction|particle\w*|coupl\w*|combust\w*|fsi)\b',
    'output': r'输出|记录|保存|测点|探针|时间历程|时程|\b(output|writ\w*|record\w*|probe\w*|sampling)\b',
    'numerics': r'时间步|步长|稳定|停止|发散|\b(timestep|time step|courant|stabil\w*|diverg\w*|stop\w*)\b',
    'workflow': r'步骤|脚本|流程|初始化|\b(workflow|allrun|script|initializ\w*)\b',
}
# Conventional input names are lookup hints, never proof of successful execution.
UTILITY_INPUTS = {
    'blockMesh': ['system/blockMeshDict'],
    'snappyHexMesh': ['system/snappyHexMeshDict'],
    'surfaceFeatures': ['system/surfaceFeaturesDict'],
    'setFields': ['system/setFieldsDict'],
    'setRefinedFields': ['system/setFieldsDict'],
    'topoSet': ['system/topoSetDict'],
    'createBaffles': ['system/createBafflesDict'],
    'decomposePar': ['system/decomposeParDict'],
}


def wire(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), sort_keys=True)


def sha(value):
    return hashlib.sha256(value if isinstance(value, bytes) else wire(value).encode()).hexdigest()


def roles(path, scope):
    name = Path(path).name
    if path.startswith('manual/'):
        return ['manual']
    if name == 'README.md':
        return ['overview']
    if name.startswith('Allrun'):
        return ['workflow']
    if name in ('blockMeshDict', 'snappyHexMeshDict', 'surfaceFeaturesDict', 'topoSetDict', 'createBafflesDict'):
        return ['geometry', 'boundary'] if scope == 'boundary' else ['geometry']
    if name == 'setFieldsDict' or scope == 'internalField':
        return ['initialization']
    if scope.startswith('boundaryField'):
        return ['boundary']
    if name == 'controlDict':
        return ['output'] if scope.startswith('functions/') else ['output', 'numerics']
    if name in ('fvSchemes', 'fvSolution', 'dynamicMeshDict'):
        return ['numerics', 'geometry'] if name == 'dynamicMeshDict' else ['numerics']
    return ['model'] if name.endswith('Properties') else ['configuration']


def build(skill=ROOT):
    """Derive scoped bundles and typed lookup edges from the published source graph."""
    skill = Path(skill)
    release = k.release_path(skill / 'index')
    k.check_release(release, skill / 'corpus')
    original = k.read_json(release / 'graph.json')
    manifest = k.read_json(release / 'manifest.json')
    cases = sorted((n['path'] for n in original['nodes'] if n['kind'] == 'case'), key=lambda x: (-len(x), x))
    nodes = {n['id']: n for n in original['nodes']}
    documents = k.read_json(release / 'documents.json')
    headers = {d['evidence']['path']: d['title'] for d in documents if d['source_scope'] == 'manual'}
    units, groups, byfile, edges = {}, defaultdict(list), defaultdict(list), []
    inventory = manifest['inventory']
    texts = {}

    def owner(path):
        return next((c for c in cases if path.startswith(c + '/')), None)

    def lines(path):
        if path not in texts:
            texts[path] = (skill / 'corpus' / path).read_text().splitlines(keepends=True)
        return texts[path]

    def add(path, start, end, scope, label='', indivisible=False):
        ls = lines(path)
        if indivisible:
            uid = sha([path, start, end, scope])[:20]
            units[uid] = {'id': uid, 'path': path, 'start': start, 'end': end,
                          'scope': scope, 'label': label, 'case': owner(path), 'roles': roles(path, scope)}
            byfile[path].append(uid)
            return
        # Split long spans only at complete line boundaries; preserve original scope.
        first, size = start, 0
        for n in range(start, end + 2):
            if n == end + 1 or (size and size + len(ls[n - 1]) > 1400):
                uid = sha([path, first, n - 1, scope])[:20]
                units[uid] = {'id': uid, 'path': path, 'start': first, 'end': n - 1,
                              'scope': scope, 'label': label, 'case': owner(path),
                              'roles': roles(path, scope)}
                byfile[path].append(uid)
                first, size = n, 0
            if n <= end:
                size += len(ls[n - 1])

    for n in nodes.values():
        if n['kind'] != 'configuration' or n['dictionary_path'].startswith('FoamFile/'):
            continue
        path = n['evidence']['path']; parts = n['dictionary_path'].split('/')
        scope = '/'.join(parts[:2]) if parts[0] == 'functions' and len(parts) > 1 else parts[0]
        if Path(path).name == 'controlDict' and len(parts) == 1:
            scope = 'control'
        groups[path, scope].append(n)
    for (path, scope), ns in sorted(groups.items()):
        start = min(n['line_start'] for n in ns); end = max(n['line_end'] for n in ns)
        # Include the actual containing dictionary header/braces where present.
        ls = lines(path)
        if any('/' in n['dictionary_path'] for n in ns):
            for a in range(start - 1, max(0, start - 5), -1):
                if ls[a - 1].strip().strip('"') == scope.split('/')[-1]:
                    start = a; break
            if end < len(ls) and ls[end].strip() in ('}', '};'):
                end += 1
        add(path, start, end, scope)
    for document in documents:
        if document['source_scope'] in ('manual','solver_code'):
            ev = document['evidence']
            add(ev['path'], ev['line_start'], ev['line_end'], 'source', document['title'], indivisible=True)
    for path in sorted(inventory):
        if not (path.startswith('tutorials/') and (Path(path).name == 'README.md' or Path(path).name.startswith('Allrun'))):
            continue
        if any(path.startswith(a + '/') for a in original.get('aliases', {})):
            continue
        ls = lines(path)
        if ls:
            add(path, 1, len(ls), 'source', headers.get(path, ''))

    def link(a, b, relation, evidence, status):
        if a != b:
            edges.append({'source': a, 'target': b, 'relation': relation,
                          'evidence': evidence, 'status': status})

    def overlapping(ev):
        return [u for u in byfile[ev['path']] if units[u]['start'] <= ev['line_end'] and units[u]['end'] >= ev['line_start']]

    outgoing = defaultdict(list)
    for e in original['edges']:
        outgoing[e['source']].append(e)
    for e in original['edges']:
        if e['relation'] == 'REFERS_TO_DEFINITION':
            for page in outgoing[e['target']]:
                if page['relation'] != 'DOCUMENTED_ON':
                    continue
                for a in overlapping(e['evidence']):
                    for b in overlapping(page['evidence']):
                        link(a, b, 'REFERS_TO_DEFINITION', [e['evidence'], page['evidence']], e['status'])
        elif e['relation'] in ('INCLUDES', 'CONFLICTS_WITH'):
            a = nodes[e['source']]; b = nodes[e['target']]
            for ua in byfile.get(a.get('path', a.get('evidence', {}).get('path')), []):
                for ub in byfile.get(b.get('path', b.get('evidence', {}).get('path')), []):
                    link(ua, ub, e['relation'], [e['evidence']], e['status'])

    for path in sorted(byfile):
        c = owner(path)
        if not c:
            continue
        workflow = byfile.get(c + '/Allrun', [])
        for uid in byfile[path]:
            for wid in workflow:
                link(uid, wid, 'CASE_SCRIPT_CONTEXT', [], 'same_case_not_execution_dependency')
        if Path(path).name.startswith('Allrun'):
            for n, line in enumerate(lines(path), 1):
                match = re.search(r'\b(?:runApplication|runParallel)\s+(\w+)\b', line)
                if not match or line.lstrip().startswith('#'):
                    continue
                # Overrides and region/cwd expressions require runtime resolution.
                if re.search(r'-(?:dict|region)\b', line) or '$' in line:
                    continue
                for suffix in UTILITY_INPUTS.get(match[1], []):
                    target = c + '/' + suffix
                    ev = {'path': path, 'line_start': n, 'line_end': n, 'sha256': inventory[path]}
                    for uid in overlapping(ev):
                        for other in byfile.get(target, []):
                            link(uid, other, 'UTILITY_INPUT_CANDIDATE', [ev], 'conventional_name_runtime_unverified')
        if Path(path).name == 'controlDict':
            controls = [u for u in byfile[path] if units[u]['scope'] == 'control']
            for uid in byfile[path]:
                if units[uid]['scope'].startswith('functions/'):
                    for cid in controls:
                        link(uid, cid, 'SEPARATE_OUTPUT_CONTROLS', [], 'distinct_dictionary_scopes')
    unique = {wire(e): e for e in edges}
    result = {'version': VERSION, 'builder_sha256': sha(Path(__file__).read_bytes()),
              'base_snapshot': original['snapshot'], 'inventory': inventory,
              'aliases': original.get('aliases', {}), 'cases': cases,
              'units': sorted(units.values(), key=lambda u: u['id']),
              'edges': [unique[e] for e in sorted(unique)],
              'issues': original['issues'],
              'terms': k.read_json(skill / 'references/terms.json'),
              'construction_api_tokens': 0}
    result['snapshot'] = sha(result)
    return result


class EvidenceSearch:
    def __init__(self, graph=None, skill=ROOT):
        self.skill = Path(skill)
        self.graph = graph if graph is not None else build(self.skill)
        self.units = {u['id']: u for u in self.graph['units']}
        self.adj = defaultdict(list)
        for e in self.graph['edges']:
            self.adj[e['source']].append(e)
        self.texts = {}
        self.validate()
        self.terms = {}
        for uid, u in self.units.items():
            self.terms[uid] = Counter(k.tokens(u['scope'] + ' ' + u['label'] + ' ' + self.raw(u)))
        self.df = Counter(t for terms in self.terms.values() for t in terms)
        self.avg = sum(sum(t.values()) for t in self.terms.values()) / max(1, len(self.terms))

    def validate(self):
        if self.graph['version'] != VERSION or self.graph['builder_sha256'] != sha(Path(__file__).read_bytes()):
            raise ValueError('bundle builder changed; rebuild derived index')
        if sha({key: value for key, value in self.graph.items() if key != 'snapshot'}) != self.graph['snapshot']:
            raise ValueError('bundle index digest mismatch')
        if k.scan(self.skill / 'corpus') != self.graph['inventory']:
            raise ValueError('corpus changed; rebuild indexes')
        if k.read_json(self.skill / 'references/terms.json') != self.graph['terms']:
            raise ValueError('terminology changed; rebuild derived index')
        if k.read_json(self.skill / 'index/current.json')['snapshot'] != self.graph['base_snapshot']:
            raise ValueError('structural index changed; rebuild derived index')
        for path in {u['path'] for u in self.units.values()}:
            p = k.confined(self.skill / 'corpus', path)
            self.texts[path] = p.read_text().splitlines(keepends=True)
        for u in self.units.values():
            if not 1 <= u['start'] <= u['end'] <= len(self.texts[u['path']]):
                raise ValueError('invalid evidence span')

    def raw(self, unit):
        return ''.join(self.texts[unit['path']][unit['start'] - 1:unit['end']])

    def query_terms(self, text):
        text = re.sub(r'(?<=\d)[x×](?=\d)', ' by ', text)
        q = dict.fromkeys(k.tokens(text), 1.)
        lower = text.casefold()
        for group in self.graph['terms']:
            if any(x.casefold() in lower if re.search('[\u4e00-\u9fff]', x) else
                   re.search(r'(?<!\w)' + re.escape(x.casefold()) + r'(?!\w)', lower) for x in group):
                for t in k.tokens(' '.join(group)):
                    q[t] = max(q.get(t, 0), .4)
        return q

    def search(self, query, strategy='graph', budget=6000, case=None):
        if not isinstance(query, str) or not query.strip() or len(query) > 32768:
            raise ValueError('query must contain 1..32768 characters')
        if strategy not in ('text', 'files', 'graph') or type(budget) is not int or not 1000 <= budget <= 24000:
            raise ValueError('invalid strategy or character budget (1000..24000)')
        self.validate()
        if case:
            case = 'tutorials/' + case.removeprefix('tutorials/')
            case = self.graph['aliases'].get(case, case)
            if case not in self.graph['cases']:
                raise ValueError('case_unavailable')
        q = self.query_terms(query); scores = {}
        for uid, terms in self.terms.items():
            if case and self.units[uid]['case'] not in (case, None):
                continue
            length = sum(terms.values()); score = 0.
            for t, weight in q.items():
                tf = terms.get(t, 0)
                if tf:
                    idf = math.log(1 + (len(self.units) - self.df[t] + .5) / (self.df[t] + .5))
                    score += weight * idf * tf * 2.2 / (tf + 1.2 * (.25 + .75 * length / self.avg))
            if score:
                scores[uid] = score
        ranked = sorted(scores, key=lambda uid: (-scores[uid], uid))
        peak = max(scores.values(), default=1)
        # Candidate choice is shared across all three strategies, prior to expansion.
        case_scores = {}
        for uid in ranked:
            u = self.units[uid]
            if u['case']:
                value = scores[uid] * (1.2 if 'overview' in u['roles'] else 1.)
                case_scores[u['case']] = max(case_scores.get(u['case'], 0), value)
        candidates = [case] if case else sorted(case_scores, key=lambda c: (-case_scores[c], c))[:2]
        # Locate candidates first, then gather evidence from those cases and the manual.
        # Apply the same scope to all arms so file/graph expansion is the only difference.
        scores = {uid: score for uid, score in scores.items() if self.units[uid]['case'] in (None, *candidates)}
        ranked = [uid for uid in ranked if uid in scores]
        desired = {r for r, pattern in ROLE_TERMS.items() if re.search(pattern, query, re.I)}
        if desired & {'geometry', 'initialization', 'boundary'}:
            desired.add('workflow')
        pool = {uid: {'rank': s / peak, 'via': 'lexical'} for uid, s in scores.items()}
        if ranked and strategy in ('files', 'graph'):
            for uid, u in self.units.items():
                if u['case'] not in candidates:
                    continue
                bonus = .15
                if strategy == 'graph' and desired.intersection(u['roles']):
                    bonus = .55
                rank = scores.get(uid, 0) / peak + bonus
                pool[uid] = {'rank': rank, 'via': 'case_scope' if strategy == 'files' else 'case_configuration_role'}
        trace = {}
        if strategy == 'graph':
            starts = ranked[:4] + sorted((u for u in pool if self.units[u]['case'] in candidates),
                                        key=lambda uid: (-pool[uid]['rank'], uid))[:8]
            for uid in starts:
                queue = [(uid, [], {uid})]
                while queue:
                    src, chain, seen = queue.pop(0)
                    if len(chain) == 2:
                        continue
                    for edge in self.adj[src]:
                        dst = edge['target']; u = self.units[dst]
                        if dst in seen or u['case'] not in (None, *candidates):
                            continue
                        route = chain + [edge]
                        relevance = bool(desired.intersection(u['roles']))
                        bonus = .6 if relevance or edge['relation'] in ('CONFLICTS_WITH', 'SEPARATE_OUTPUT_CONTROLS') else .2
                        rank = scores.get(dst, 0) / peak + bonus
                        if rank > pool.get(dst, {}).get('rank', -1):
                            pool[dst] = {'rank': rank, 'via': edge['relation']}
                            trace[dst] = route
                        queue.append((dst, route, seen | {dst}))
        # Same diversity and packing policy for all strategies. No inferred summaries.
        result = {'status': 'ok' if ranked else 'no_lexical_match', 'snapshot': self.graph['snapshot'],
                  'strategy': strategy, 'candidate_cases': candidates, 'sources': {}, 'evidence': [],
                  'limits': ['Candidate relevance is not physical applicability.',
                             'Static declarations and script occurrences; execution and complete coverage unverified.']}
        used = defaultdict(set); path_ids = {}; selected = []; count_roles = Counter(); count_cases = Counter()
        content_seen = set()
        pending = dict(pool)
        while pending:
            def priority(uid):
                u = self.units[uid]
                redundancy = max((count_roles[(u['case'], r)] for r in u['roles']), default=0)
                return pool[uid]['rank'] / (1 + .35 * redundancy + .15 * count_cases[u['case']])
            uid = min(pending, key=lambda x: (-priority(x), x)); pending.pop(uid)
            u = self.units[uid]; path = u['path']
            content = self.raw(u)
            if content in content_seen:
                continue
            if any(n in used[path] for n in range(u['start'], u['end'] + 1)):
                continue
            sid = path_ids.get(path, 's' + str(len(path_ids) + 1))
            item = {'source': sid, 'start': u['start'], 'end': u['end'],
                    'scope': u['scope'], 'text': content, 'via': pool[uid]['via']}
            sources = {**result['sources'], sid: {'path': path, 'sha256': self.graph['inventory'][path]}}
            proposal = {**result, 'sources': sources, 'evidence': result['evidence'] + [item]}
            if len(wire(proposal)) > budget:
                continue
            result = proposal; path_ids[path] = sid; selected.append(uid)
            content_seen.add(content)
            used[path].update(range(u['start'], u['end'] + 1)); count_cases[u['case']] += 1
            count_roles.update((u['case'], r) for r in u['roles'])
        if ranked and not result['evidence']:
            result['status'] = 'budget_too_small_for_evidence'
        assert len(wire(result)) <= budget
        audit = {'query': query, 'desired_roles': sorted(desired), 'selected_units': selected,
                 'selected_paths': {uid: trace[uid] for uid in selected if uid in trace},
                 'candidate_units': len(pool), 'returned_characters': len(wire(result)),
                 'construction_api_tokens': 0, 'retrieval_api_tokens': 0}
        return result, audit


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=['build', 'search'])
    p.add_argument('--index', type=Path, help='Optional external derived graph JSON; required for build')
    p.add_argument('--query', default=''); p.add_argument('--case')
    p.add_argument('--strategy', choices=['text', 'files', 'graph'], default='graph')
    p.add_argument('--budget', type=int, default=6000); p.add_argument('--audit', type=Path)
    args = p.parse_args()
    if args.action == 'build':
        if args.index is None:
            p.error('build requires --index outside the source project')
        graph = build(); k.write_json(args.index, graph)
        print(wire({'status': 'built', 'snapshot': graph['snapshot'], 'units': len(graph['units']),
                    'edges': len(graph['edges']), 'construction_api_tokens': 0}))
        return
    graph = k.read_json(args.index) if args.index else None
    packet, audit = EvidenceSearch(graph).search(args.query, args.strategy, args.budget, args.case)
    if args.audit:
        k.write_json(args.audit, audit)
    print(wire(packet))


if __name__ == '__main__':
    main()
