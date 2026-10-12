"""全图来源、双侧关联与声明状态验证；只读取构图语料，不接收题目或gold。"""
from __future__ import annotations
import argparse
from collections import Counter
import json
from pathlib import Path
from candidate_graph import scoped_roles_match
from candidate_hybrid import sha


def verify(graph_path,structure):
    graph=json.loads(graph_path.read_text());manifest=json.loads((structure/'manifest.json').read_text())
    if graph['corpus_id']!=manifest['corpus_id'] or not graph['coverage']['semantic_complete']:
        raise ValueError('coverage or corpus mismatch')
    root=Path(manifest['corpus_root']);files={};checked=set();bilateral=Counter()
    def anchor(a):
        identity=json.dumps(a,sort_keys=True)
        if identity in checked:return
        path=root/a['path']
        if not path.resolve().is_relative_to(root.resolve()):raise ValueError('evidence outside corpus')
        if a['path'] not in files:
            raw=path.read_bytes();files[a['path']]=(raw,raw.decode().splitlines())
        raw,lines=files[a['path']];start,end=a['start'],a['end']
        if type(start) is not int or type(end) is not int or not 1<=start<=end<=len(lines):raise ValueError('invalid evidence range')
        if a.get('source_sha256') and a['source_sha256']!=sha(raw):raise ValueError('evidence source hash drift')
        if a.get('quote'):
            if a['quote'] not in '\n'.join(lines[start-1:end]):raise ValueError('evidence quote outside cited span')
            if a.get('quote_sha256') and sha('\n'.join(lines[start-1:end]).encode())!=a['quote_sha256']:raise ValueError('quote hash drift')
        checked.add(identity)
    nodes=graph['nodes'];ids=set()
    inventory={p.relative_to(root).as_posix():p for p in root.rglob('*') if p.is_file()}
    registered={n['path'] for n in nodes.values() if n['kind']=='file'}
    if registered!=set(inventory) or len(inventory)!=graph['coverage']['inventory_files']:raise ValueError('physical file inventory gap')
    for n in nodes.values():
        for a in n['evidence']:anchor(a)
    for e in graph['edges']:
        if e['id'] in ids or e['source'] not in nodes or e['target'] not in nodes:raise ValueError('invalid edge identity')
        ids.add(e['id'])
        target=nodes[e['target']]
        if e['status']=='source_supported_declaration' and target['kind']=='conditional_assertion' and target.get('subject_role'):
            if nodes[e['source']].get('role')!=target['subject_role']:raise ValueError('assertion subject role mismatch')
        for a in e['evidence']:anchor(a)
        if e.get('conditions') and e.get('condition_satisfied') is True:raise ValueError('construction asserted runtime condition')
        if e.get('instance_evidence') and e.get('definition_evidence'):
            bilateral[e['relation']]+=1
            for a in e['instance_evidence']+e['definition_evidence']:anchor(a)
            if e['relation']=='DOCUMENTED_BY' and not scoped_roles_match(nodes[e['source']],nodes[e['target']]):
                raise ValueError('bilateral relation without role match')
    empty=[];binary=[]
    for path,p in inventory.items():
        try:lines=p.read_bytes().decode().splitlines()
        except UnicodeDecodeError:binary.append(path);continue
        if not lines:empty.append(path)
        elif path not in files:raise ValueError('readable nonempty file has no graph evidence')
    return {'empty_readable_files':sorted(empty),'binary_inventory_files':len(binary),'status':'passed','graph_sha256':sha(graph_path.read_bytes()),'corpus_id':graph['corpus_id'],
            'coverage':graph['coverage'],'nodes':len(nodes),'edges':len(ids),'unique_anchors_verified':len(checked),
            'anchored_readable_files':len(files),'relation_counts':dict(Counter(e['relation'] for e in graph['edges'])),
            'bilateral_relation_counts':dict(bilateral),
            'scope':'all accepted graph anchors and bilateral role identities checked; no claim of complete semantic recall or runtime activation'}


if __name__=='__main__':
    cli=argparse.ArgumentParser(description=__doc__);cli.add_argument('--graph',type=Path,required=True)
    cli.add_argument('--structure',type=Path,required=True);cli.add_argument('--output',type=Path,required=True);a=cli.parse_args()
    result=verify(a.graph,a.structure);a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(result,ensure_ascii=False))
