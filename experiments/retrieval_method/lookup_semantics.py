"""Reviewed source graph for the lookup semantics of concrete edit targets."""
import hashlib
import json
from pathlib import Path
import re


def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()


class LookupSemantics:
    def __init__(self, manifest):
        self.root=Path(manifest).resolve().parent
        self.graph=json.loads(Path(manifest).read_text())
        if digest({k:v for k,v in self.graph.items() if k!='snapshot'})!=self.graph['snapshot']:
            raise ValueError('lookup graph digest changed')
        self.nodes={n['id']:n for n in self.graph['nodes']}
        if len(self.nodes)!=len(self.graph['nodes']):raise ValueError('duplicate lookup node')
        for node in self.nodes.values():
            if node['review']!='accept':raise ValueError('unreviewed lookup node')
            for ev in node['evidence']:
                lines=self.read_file(ev['path']).splitlines(keepends=True)
                if not 1<=ev['start']<=ev['end']<=len(lines):raise ValueError('invalid lookup evidence range')
                if not ev['quote'] or ev['quote'] not in ''.join(lines[ev['start']-1:ev['end']]):raise ValueError('lookup evidence quote changed')
            if not node['evidence']:raise ValueError('lookup node lacks evidence')
        for edge in self.graph['edges']:
            if edge['source'] not in self.nodes or edge['target'] not in self.nodes:raise ValueError('dangling lookup edge')
            if edge['review']!='accept' or edge['relation']!='CALLS':raise ValueError('unreviewed lookup edge')
            if edge['evidence'] not in self.nodes[edge['source']]['evidence']:raise ValueError('lookup edge lacks caller evidence')

    def read_file(self,path):
        if path not in self.graph['inventory']:raise ValueError('unindexed lookup source')
        file=(self.root/path).resolve()
        if not file.is_relative_to(self.root):raise ValueError('lookup source escapes root')
        raw=file.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=self.graph['inventory'][path]:raise ValueError('lookup source changed')
        return raw.decode()

    def reference(self,packet):
        if packet.get('status')!='conditional_edit_drafts':return None
        binding=self.graph['binding']
        # Require the same reviewed dependency context, not merely a matching filename.
        if packet.get('condition_snapshot')!=binding['condition_snapshot']:return None
        start=binding['entry_node'];end=binding['rule_node'];seen=set();queue=[start]
        while queue:
            node=queue.pop()
            if node in seen:continue
            seen.add(node)
            queue.extend(e['target'] for e in self.graph['edges'] if e['source']==node)
        if end not in seen:return None
        fields=[]
        for condition in packet.get('conditional_drafts',[]):
            if condition['id']!=binding['condition']:continue
            for edit in condition.get('preparation_edits',condition.get('edits_if_true',[])):
                parts=edit['entry'].split('/')
                if (edit['path']==binding['path'] and len(parts)==3
                        and parts[0]==binding['parent'] and parts[-1]==binding['leaf']
                        and re.fullmatch(r'[A-Za-z_]\w*',parts[1]) and edit['value'] is not None):
                    fields.append('/'.join(parts[:2]))
        if not fields:return None
        return {'relation':'RESOLVES_BY','targets':{binding['path']:sorted(set(fields))},
                'rule':self.nodes[end]['claim'],'source':'lookup_semantics/rule',
                'snapshot':self.graph['snapshot']}

    def rule_text(self):
        lines=[self.graph['scope'], 'Snapshot: '+self.graph['snapshot']]
        for node in self.graph['nodes']:
            lines += ['', node['id']+': '+node['claim']]
            for ev in node['evidence']:
                lines += ['Source: lookup_semantics/'+ev['path']+':'+str(ev['start'])+'-'+str(ev['end']), ev['quote']]
        lines += ['', 'Reviewed edges:']
        lines += [e['source']+' --'+e['relation']+'--> '+e['target'] for e in self.graph['edges']]
        return '\n'.join(lines)+'\n'
