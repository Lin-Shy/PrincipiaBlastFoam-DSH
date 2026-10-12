"""Export offline, source-inspectable HTML/JSON/SVG for both published graph layers."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import html
import json
import math
from pathlib import Path

import evidence_bundle as bundle
import global_graph

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / 'references/graph-viewer.html'
REFERENCE = 'https://github.com/Graphify-Labs/graphify/blob/v8/graphify/exporters/html.py'


def safe_json(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':')).replace('<', '\\u003c').replace('\u2028', '\\u2028').replace('\u2029', '\\u2029')


def collect(skill=ROOT, index=None):
    skill = Path(skill)
    engine = bundle.EvidenceSearch(json.loads(Path(index).read_text()) if index else None, skill)
    graph = engine.graph
    sources = {}

    def source(ev):
        path = ev['path']; a = ev.get('start', ev.get('line_start')); z = ev.get('end', ev.get('line_end'))
        p = bundle.k.confined(skill / 'corpus', path)
        raw = p.read_bytes(); expected = graph['inventory'].get(path)
        if expected is None or hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError('source absent or changed: ' + path)
        text = raw.decode('utf-8'); ls = text.splitlines(keepends=True)
        if type(a) is not int or type(z) is not int or not 1 <= a <= z <= len(ls):
            raise ValueError('invalid source range: ' + path)
        sources[path] = {'sha256': expected, 'text': text}
        return {'path': path, 'start': a, 'end': z}

    nodes = []
    for u in graph['units']:
        nodes.append({'id': u['id'], 'label': Path(u['path']).name + ' · ' + u['scope'],
            'kind': '配置片段' if u['case'] else '手册片段', 'group': u['case'] or 'manual',
            'cases': [u['case'] or 'manual'], 'scope': u['scope'], 'roles': u['roles'],
            'description': u['label'], 'status': '原文定位已校验；静态声明，未执行验证',
            'sources': [source(u)]})
    edges = [{'id': 'd' + str(i), 'source': e['source'], 'target': e['target'],
              'relation': e['relation'], 'status': e['status'],
              'sources': [source(ev) for ev in e['evidence']]} for i, e in enumerate(graph['edges'])]
    derived = {'id': 'configuration', 'name': '配置证据图', 'snapshot': graph['snapshot'],
               'description': '按字典作用域与来源连接。脚本上下文、惯例输入均不表示已验证的执行依赖。',
               'nodes': nodes, 'edges': edges}
    original = global_graph.GlobalGraph(skill)
    cases = defaultdict(set)
    for e in original.graph['edges']:
        card = original.cards[e['target']]
        cases[e['source']].add(card['case'] or 'manual')
    snodes = []
    for e in original.graph['entities']:
        cs = sorted(cases[e['id']])
        snodes.append({'id': e['id'], 'label': e['name'], 'kind': e['kind'],
            'group': cs[0] if len(cs) == 1 else 'shared', 'cases': cs,
            'scope': e.get('namespace', ''), 'roles': [], 'description': '',
            'status': '来源卡片中的实体；未独立完成语义审核', 'sources': []})
    for c in original.graph['cards']:
        snodes.append({'id': c['id'], 'label': c['title'], 'kind': '来源卡片',
            'group': c['case'] or 'manual', 'cases': [c['case'] or 'manual'], 'scope': c['relation'],
            'roles': [], 'description': c['subject'] + ' → ' + c['object'],
            'conditions': c['conditions_zh'], 'status': c['review'],
            'visual_check_required': c.get('visual_check_required', False),
            'sources': [source(ev) for ev in c['evidence']]})
    sedges = [{'id': 's' + str(i), **e, 'status': '候选来源关系；不是已审核物理事实', 'sources': []}
              for i, e in enumerate(original.graph['edges'])]
    semantic = {'id': 'semantic', 'name': '原有语义定位图', 'snapshot': original.graph['snapshot'],
                'description': '实体与来源卡片构成二部图。连线代表原有卡片关系，保留抽取条件和审核状态。',
                'nodes': snodes, 'edges': sedges}
    for layer in (derived, semantic):
        ids = {n['id'] for n in layer['nodes']}
        if len(ids) != len(layer['nodes']) or any(e['source'] not in ids or e['target'] not in ids for e in layer['edges']):
            raise ValueError('duplicate nodes or dangling edges')
    return {'schema': 'blastfoam-visualization-v1', 'title': 'blastFoam 知识图谱',
            'grouping': '按案例与手册来源分组；没有运行社区发现算法。',
            'reference': REFERENCE, 'layers': [derived, semantic], 'sources': sources}


def overview_svg(layer):
    groups = Counter(n['group'] for n in layer['nodes'])
    byid = {n['id']: n['group'] for n in layer['nodes']}
    connections = Counter((byid[e['source']], byid[e['target']]) for e in layer['edges'] if byid[e['source']] != byid[e['target']])
    names = sorted(groups); width = 1500; height = max(650, math.ceil(len(names) / 4) * 105 + 170)
    xy = {g: (190 + (i % 4) * 370, 165 + (i // 4) * 105) for i, g in enumerate(names)}
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
             '<rect width="100%" height="100%" fill="#f3f6fa"/>',
             '<g font-family="sans-serif" fill="#172b45">',
             '<text x="40" y="45" font-size="26">blastFoam · 配置证据图来源总览</text>',
             '<text x="40" y="77" font-size="15">节点按案例／手册聚合；连线为跨组来源关系。组内关系省略，交互页面保留完整图。</text>']
    for (a, z), count in connections.items():
        x, y = xy[a]; xx, yy = xy[z]
        parts.append(f'<path d="M{x},{y} Q{(x+xx)/2},{min(y,yy)-40} {xx},{yy}" fill="none" stroke="#acbacb" opacity="0.3" stroke-width="{min(4,1+math.log1p(count)/2):.2f}"/>')
    for g, (x, y) in xy.items():
        color = '#157d89' if g == 'manual' else '#4269b5'
        label = g.removeprefix('tutorials/')
        if len(label) > 43:
            label = label[:20] + '…' + label[-20:]
        parts.extend([f'<circle cx="{x}" cy="{y}" r="17" fill="{color}"/>',
                      f'<text x="{x}" y="{y+36}" text-anchor="middle" font-size="11">{html.escape(label)}</text>',
                      f'<text x="{x}" y="{y+54}" text-anchor="middle" fill="#667890" font-size="11">{groups[g]} 个证据单元</text>'])
    return '\n'.join(parts + ['</g></svg>'])


def export(output, skill=ROOT, index=None):
    output = Path(output)
    if output.exists() and any(output.iterdir()):
        raise ValueError('choose a new or empty output directory')
    data = collect(skill, index)
    template = TEMPLATE.read_text()
    if template.count('__GRAPH_DATA__') != 1:
        raise ValueError('invalid viewer template')
    output.mkdir(parents=True, exist_ok=True)
    (output / 'graph.html').write_text(template.replace('__GRAPH_DATA__', safe_json(data)))
    (output / 'graph.json').write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    (output / 'overview.svg').write_text(overview_svg(data['layers'][0]))
    summary = {'status': 'exported', 'layers': [{'name': l['name'], 'nodes': len(l['nodes']),
        'edges': len(l['edges']), 'snapshot': l['snapshot']} for l in data['layers']],
        'source_files': len(data['sources']), 'offline': True, 'api_calls': 0,
        'reference': REFERENCE, 'grouping': data['grouping'],
        'files': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in output.iterdir() if p.is_file()}}
    (output / 'manifest.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n')
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--index', type=Path, help='Optional frozen derived configuration index')
    args = parser.parse_args()
    print(json.dumps(export(args.output, index=args.index), ensure_ascii=False, indent=2))
