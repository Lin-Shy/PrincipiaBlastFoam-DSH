"""导出章节/证据与条件语义图，离线阅读 Markdown、公式和来源。"""
import argparse
import json
from pathlib import Path
import shutil

import manual_graph as g
from export_visualization import safe_json


def collect(graph, semantic, source, review=None):
    g.validate(graph, source)
    byid = {n['id']: n for n in graph['nodes']}
    sources = {p: {'sha256': h, 'text': (source/p).read_bytes().decode()}
               for p, h in graph['inventory'].items() if p.endswith('.md')}
    def spans(n):
        if n.get('path') not in sources:
            return []
        return [{'path': n['path'], 'start': n.get('start', 1),
                 'end': n.get('end', len(sources[n['path']]['text'].splitlines()))}]
    nodes = []
    for n in graph['nodes']:
        hierarchy = byid[n['section']]['hierarchy'] if n['kind'] == 'evidence' else n.get('hierarchy', [])
        nodes.append({'id': n['id'], 'label': n['label'], 'kind': n['kind'], 'group': n['path'],
                      'cases': [n['path']], 'scope': ' > '.join(hierarchy), 'roles': [],
                      'image_path': n['path'] if n['kind'] == 'figure' else None,
                      'description': '', 'status': '原文与来源范围已校验', 'sources': spans(n)})
    edges = [{'id': 'base-'+str(i), **e, 'status': '文档结构或明示引用',
              'sources': [s for eid in e.get('evidence', []) for s in spans(byid[eid])]} for i, e in enumerate(graph['edges'])]
    layers = [{'id': 'configuration', 'name': '章节与原文证据图', 'snapshot': graph['snapshot'],
               'description': '按章节、小节及完整原文单元组织。层级关联不自动表示物理条件继承。',
               'nodes': nodes, 'edges': edges}]
    if semantic:
        if semantic['foundation_snapshot'] != graph['snapshot']:
            raise ValueError('semantic snapshot does not match foundation')
        decisions = {d['fact']: d for d in (review or {}).get('decisions', [])}
        if review and review['semantic_snapshot'] != semantic['snapshot']:
            raise ValueError('review snapshot mismatch')
        snodes = {}; sedges = []
        for f in semantic['facts']:
            decision = decisions.get(f['id'], {'status': 'unreviewed', 'reason': '尚未完成语义复核'})
            source_spans = [{'path': e['path'], 'start': e['line_start'], 'end': e['line_end']} for e in f['evidence']]
            for entity in (f['subject'], f['object']):
                section = byid[entity['scope']]
                snodes[entity['id']] = {'id': entity['id'], 'label': entity['name'], 'kind': entity['kind'],
                    'group': section['label'], 'cases': [section['label']], 'scope': ' > '.join(section['hierarchy']),
                    'roles': [], 'description': '', 'status': '实体按原文名、类别和章节作用域区分', 'sources': spans(section)}
            snodes[f['id']] = {'id': f['id'], 'label': f['summary_zh'], 'kind': '条件关系',
                'group': byid[f['section']]['label'], 'cases': [byid[f['section']]['label']],
                'scope': f['relation'], 'roles': [], 'description': f['subject']['name']+' → '+f['object']['name'],
                'conditions': f['conditions_zh'], 'status': decision['status']+' · '+decision['reason'], 'sources': source_spans}
            sedges += [{'id': f['id']+':subject', 'source': f['subject']['id'], 'target': f['id'],
                        'relation': f['relation'], 'status': decision['status'], 'sources': source_spans},
                       {'id': f['id']+':object', 'source': f['id'], 'target': f['object']['id'],
                        'relation': 'OBJECT', 'status': decision['status'], 'sources': source_spans}]
        chapters = sorted({byid[f['section']]['path'].split('_', 1)[0].lstrip('0') for f in semantic['facts']},
                          key=lambda s: (not s.isdigit(), int(s) if s.isdigit() else s))
        semantic_name = '第'+ '、'.join(chapters)+'章条件关系图' if chapters else '条件关系图'
        layers.append({'id': 'semantic', 'name': semantic_name, 'snapshot': semantic['snapshot'],
                       'description': '关系通过原文出处校验；审核状态逐条展示。拒绝关系保留可审阅，但不参与查询。',
                       'nodes': list(snodes.values()), 'edges': sedges})
    return {'schema': 'manual-viewer-v1', 'layers': layers, 'sources': sources,
            'grouping': '章节与原文作用域', 'render_markdown': True}


def export(output, graph, semantic=None, source=g.ROOT/'corpus/manual/markdown', katex_dist=None, review=None):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    data = collect(graph, semantic, Path(source), review)
    if katex_dist:
        dist = Path(katex_dist)
        if not (dist/'katex.min.js').is_file() or not (dist/'katex.min.css').is_file():
            raise ValueError('KaTeX dist directory required')
        shutil.copytree(dist, output/'assets/katex', dirs_exist_ok=True)
        license_path = dist.parent/'LICENSE'
        if license_path.exists():
            shutil.copyfile(license_path, output/'assets/katex/LICENSE')
    if not (output/'assets/katex/katex.min.js').exists():
        raise ValueError('--katex-dist required for first offline export')
    for image in (Path(source)/'figures').glob('*'):
        if image.is_file():
            (output/'figures').mkdir(exist_ok=True)
            shutil.copyfile(image, output/'figures'/image.name)
    template = (g.ROOT/'references/graph-viewer.html').read_text()
    semantic_name = next((layer['name'] for layer in data['layers'] if layer['id']=='semantic'), '条件关系图')
    template = template.replace('新增配置证据图', '章节与原文证据图').replace('原有语义定位图', semantic_name)
    template = template.replace('<option value="files">文件总览</option><option value="nodes">片段／实体</option>',
                                '<option value="nodes">章节／证据／实体</option><option value="files">文件总览</option>')
    template = template.replace('全部案例与手册', '全部章节').replace('来源分组', '章节分组')
    template = template.replace('案例内同时显示相邻手册依据', '同时显示相邻来源')
    template = template.replace('颜色按案例与手册来源分组', '颜色按章节与来源作用域分组')
    template = template.replace('例如 pressureProbes、flap', '例如 JWL、tabulatedMG')
    assets = '<link rel="stylesheet" href="assets/katex/katex.min.css"><script src="assets/katex/katex.min.js"></script>'
    assets += '<style>.markdown-view{overflow:auto;font-size:13px}.markdown-view table{border-collapse:collapse;width:100%;font-size:12px}.markdown-view th,.markdown-view td{border:1px solid #dce5ef;padding:5px}.markdown-view img{max-width:100%}.markdown-view .katex-display{overflow-x:auto;overflow-y:hidden;padding:8px 0}.math-error{color:#a11}.right{min-width:0}@media(min-width:1100px){main{grid-template-columns:265px minmax(300px,1fr) minmax(420px,38vw)}}</style>'
    assets += '<script>'+ (g.ROOT/'references/manual-markdown-renderer.js').read_text()+'</script>'
    template = template.replace('</head>', assets+'</head>')
    needle = "details.append(el('pre',text),el('div','SHA-256 '+src.sha256,'meta'));"
    replacement = "details.append(renderManualMarkdown(src.text.split(/\\r?\\n/).slice(s.start-1,s.end).join('\\n')));const raw=el('details');raw.append(el('summary','Markdown 原文（带行号）'),el('pre',text));details.append(raw,el('div','SHA-256 '+src.sha256,'meta'));"
    if needle not in template:
        raise ValueError('viewer source panel changed; update adapter')
    template = template.replace(needle, replacement)
    template = template.replace("if(!n.sources.length)panel.append", "if(n.image_path){const picture=el('img');picture.src=n.image_path;picture.alt=n.label;picture.style.maxWidth='100%';panel.append(picture)}if(!n.sources.length&&!n.image_path)panel.append")
    (output/'index.html').write_text(template.replace('__GRAPH_DATA__', safe_json(data)))
    g.write(output/'graph.json', data)
    manifest = {'layers': [{'name': l['name'], 'nodes': len(l['nodes']), 'edges': len(l['edges'])} for l in data['layers']],
                'source_files': len(data['sources']), 'offline': True,
                'files': {p.relative_to(output).as_posix(): g.sha(p.read_bytes()) for p in sorted(output.rglob('*')) if p.is_file() and p.name != 'manifest.json'}}
    g.write(output/'manifest.json', manifest)
    return manifest


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--foundation', type=Path, required=True)
    p.add_argument('--semantic', type=Path)
    p.add_argument('--review', type=Path)
    p.add_argument('--source', type=Path, default=g.ROOT/'corpus/manual/markdown')
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--katex-dist', type=Path)
    args = p.parse_args()
    result = export(args.output, json.loads(args.foundation.read_text()),
                    json.loads(args.semantic.read_text()) if args.semantic else None,
                    args.source, args.katex_dist, json.loads(args.review.read_text()) if args.review else None)
    print(g.encoded({k: v for k, v in result.items() if k != 'files'}))
