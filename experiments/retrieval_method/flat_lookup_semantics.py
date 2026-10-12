"""Evidence-parity runtime ablation: a materialized rule without graph traversal.

Compilation consumes the reviewed graph once. This is not a graph-free knowledge
construction baseline; the rest of the locator is also shared with the graph arm.
"""
import hashlib
import json
from pathlib import Path
import re


def digest(data):
    return hashlib.sha256(json.dumps(data,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def materialize(graph):
    binding=graph.graph['binding'];seen=set();pending=[binding['entry_node']]
    while pending:
        node=pending.pop()
        if node in seen:continue
        seen.add(node)
        pending.extend(e['target'] for e in graph.graph['edges'] if e['source']==node)
    record={'binding':{k:v for k,v in binding.items() if k not in ('entry_node','rule_node')},
            'enabled':binding['rule_node'] in seen,
            'claim':graph.nodes[binding['rule_node']]['claim'],
            'evidence':[ev for n in graph.nodes.values() for ev in n['evidence']],
            'inventory':graph.graph['inventory'],'source_snapshot':graph.graph['snapshot'],
            'rule_document':graph.rule_text()}
    record['digest']=digest(record)
    return record


class FlatLookupSemantics:
    def __init__(self,manifest):
        manifest=Path(manifest).resolve();self.root=manifest.parent
        self.record=json.loads(manifest.read_text())
        if digest({k:v for k,v in self.record.items() if k!='digest'})!=self.record['digest']:
            raise ValueError('flat rule changed')
        # Adapter metadata only; no nodes, edges or traversal in this runtime.
        self.graph={'snapshot':self.record['source_snapshot']}
        if not self.record['evidence']:raise ValueError('flat rule lacks evidence')
        for ev in self.record['evidence']:
            lines=self.read_file(ev['path']).splitlines(keepends=True)
            if not 1<=ev['start']<=ev['end']<=len(lines):raise ValueError('invalid flat evidence range')
            if not ev['quote'] or ev['quote'] not in ''.join(lines[ev['start']-1:ev['end']]):
                raise ValueError('flat evidence changed')

    def read_file(self,path):
        if path not in self.record['inventory']:raise ValueError('unindexed flat source')
        file=(self.root/path).resolve()
        if not file.is_relative_to(self.root):raise ValueError('flat source escapes root')
        raw=file.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=self.record['inventory'][path]:raise ValueError('flat source changed')
        return raw.decode()

    def rule_text(self):
        return self.record['rule_document']

    def reference(self,packet):
        b=self.record['binding']
        if (not self.record['enabled'] or packet.get('status')!='conditional_edit_drafts'
                or packet.get('condition_snapshot')!=b['condition_snapshot']):return None
        targets=set()
        for c in packet.get('conditional_drafts',[]):
            if c['id']!=b['condition']:continue
            for e in c.get('preparation_edits',c.get('edits_if_true',[])):
                parts=e['entry'].split('/')
                if (e['path']==b['path'] and len(parts)==3 and parts[0]==b['parent']
                        and parts[2]==b['leaf'] and re.fullmatch(r'[A-Za-z_]\w*',parts[1])
                        and e['value'] is not None):targets.add('/'.join(parts[:2]))
        if not targets:return None
        return {'relation':'RESOLVES_BY','targets':{b['path']:sorted(targets)},
                'rule':self.record['claim'],'source':'lookup_semantics/rule',
                'snapshot':self.record['source_snapshot']}
