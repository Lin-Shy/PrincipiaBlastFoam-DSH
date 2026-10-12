"""Reviewed default-source factory route, not a live registration-table assertion."""
import hashlib,json
from collections import deque
from pathlib import Path
from experiments.retrieval_method.lookup_semantics import digest


class FactoryRoute:
    def __init__(self,manifest):
        self.root=Path(manifest).resolve().parent
        self.graph=json.loads(Path(manifest).read_text())
        if digest({k:v for k,v in self.graph.items() if k!='snapshot'})!=self.graph['snapshot']:raise ValueError('factory graph changed')
        self.nodes={n['id']:n for n in self.graph['nodes']}
        if len(self.nodes)!=len(self.graph['nodes']):raise ValueError('duplicate factory node')
        for node in self.nodes.values():
            if node['review']!='accept':raise ValueError('unreviewed factory node')
            for ev in node['evidence']:
                lines=self.read(ev['path']).splitlines(keepends=True)
                if not 1<=ev['start']<=ev['end']<=len(lines):raise ValueError('invalid factory evidence range')
                if not ev['quote'] or ev['quote'] not in ''.join(lines[ev['start']-1:ev['end']]):raise ValueError('factory source quote changed')
            if not node['evidence']:raise ValueError('missing factory evidence')
        for edge in self.graph['edges']:
            if edge['source'] not in self.nodes or edge['target'] not in self.nodes:raise ValueError('dangling factory edge')
            if edge['review']!='accept':raise ValueError('unreviewed factory edge')

    def read(self,path):
        if path not in self.graph['inventory']:raise ValueError('unindexed factory source')
        file=(self.root/path).resolve()
        if not file.is_relative_to(self.root):raise ValueError('factory source escapes root')
        raw=file.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=self.graph['inventory'][path]:raise ValueError('factory source changed')
        return raw.decode()

    def reachable(self,target=None):
        seen=set();pending=[self.graph['entry']]
        while pending:
            n=pending.pop()
            if n in seen:continue
            seen.add(n);pending.extend(e['target'] for e in self.graph['edges'] if e['source']==n)
        return (self.graph['end'] if target is None else target) in seen

    def evidence_path(self,start,target,relations=None):
        """Shortest reviewed directed path; optional relation family excludes shortcuts."""
        if start not in self.nodes or target not in self.nodes:raise ValueError('unknown factory endpoint')
        pending=deque([(start,[])]);seen={start}
        while pending:
            current,path=pending.popleft()
            if current==target:return path
            edges=sorted((e for e in self.graph['edges'] if e['source']==current
                          and (relations is None or e['relation'] in relations)),
                         key=lambda e:(e['target'],e['relation']))
            for edge in edges:
                if edge['target'] not in seen:
                    seen.add(edge['target']);pending.append((edge['target'],path+[edge]))
        return None

    def path_source(self,start,target):
        projection=self.graph.get('inline_path',{})
        relations=projection.get('relations') if (start,target)==(self.graph['entry'],self.graph['end']) else None
        edges=self.evidence_path(start,target,relations)
        if edges is None:raise ValueError('factory endpoints disconnected')
        ids=[start]+[e['target'] for e in edges]
        lines=['Snapshot: '+self.graph['snapshot'],self.graph['scope']]
        for i,node_id in enumerate(ids):
            node=self.nodes[node_id]
            lines.append(node_id+': '+node['claim'])
            for e in node['evidence']:
                lines.append('factory_route/'+e['path']+':'+str(e['start'])+'-'+str(e['end']))
            if i<len(edges):lines.append('--'+edges[i]['relation']+'-->')
        return '\n'.join(lines)+'\n'

    def reference(self,engine,packet,identity):
        if not identity or len(identity['phases'])!=2 or not self.reachable():return None
        import knowledge as k
        values={}
        for relative in ['system/controlDict','constant/phaseProperties']:
            path=packet['case']+'/'+relative
            if path not in engine.graph['inventory']:return None
            root=(engine.skill/'corpus').resolve();file=(root/path).resolve()
            if not file.is_relative_to(root):raise ValueError('case route source escapes corpus')
            raw=file.read_bytes()
            if hashlib.sha256(raw).hexdigest()!=engine.graph['inventory'][path]:raise ValueError('case route source changed')
            entries,diagnostics=k.parse_dictionary(raw.decode())
            if diagnostics:return None
            if any('@' in e['dictionary_path'] for e in entries):return None
            values[relative]={e['dictionary_path']:e['value'] for e in entries if e['resolved']}
        control=values['system/controlDict'];phases=values['constant/phaseProperties']
        if control.get('application')!='blastFoam' or 'libs' in control:return None
        if phases.get('systemType','twoPhaseCompressibleSystem')!='twoPhaseCompressibleSystem':return None
        located={x['dictionary'].split('/')[0] for x in packet.get('locations',[]) if x['path']==packet['case']+'/constant/phaseProperties'}
        if not located.intersection(identity['phases']):return None
        return {'source':'factory_route/guide','scope':'Reviewed default blastFoam two-phase source route; not live table or compatibility validation.',
                'basic_phase_flow':all(phases.get(phase+'/type')=='basic' for phase in identity['phases']),
                'fact':'Registry miss can trigger template compilation if enabled and available; compile/link can fail. const reads mu: const does not mean zero.'}

    def inline_evidence(self,include_transport=False):
        """Project the reviewed endpoint fact only when the full route reaches it."""
        if self.graph['end']!='compile_fallback' or not self.reachable():return None
        node=self.nodes.get('compile_fallback')
        if node is None:return None
        projection=self.graph.get('inline_path')
        if projection:
            edges=self.evidence_path(self.graph['entry'],self.graph['end'],projection['relations'])
            if edges is not None:
                ids=[self.graph['entry']]+[e['target'] for e in edges]
                return {'construction_path':' → '.join(self.nodes[n].get('label',n) for n in ids),
                        'source':'factory_route/path/'+self.graph['entry']+'/'+self.graph['end'],
                        'scope':projection['scope'],'source_snapshot':self.graph['snapshot']}
        result={'claim':node['claim'],
                'sources':[{'path':'factory_route/'+e['path'],'start':e['start'],'end':e['end']} for e in node['evidence']],
                'scope':'Default two-phase source; build/load/runtime unvalidated.'}
        # A separately reviewed summary must be connected to the entry route.
        # Source evidence is not a statement about whichever binary is loaded.
        flow=self.nodes.get('transport_flow_summary')
        if include_transport and flow and self.reachable(flow['id']):
            result={'transport_flow':{'claim':flow['claim'],
                'source':'factory_route/node/'+flow['id'],
                'source_snapshot':self.graph['snapshot'],
                'runtime_status':'unverified: loaded library not identified'}}
        return result

    def node_source(self,node_id):
        """Expose one reviewed fact and its source spans without the whole guide."""
        if node_id not in self.nodes:raise ValueError('unknown factory node')
        node=self.nodes[node_id]
        return json.dumps({'snapshot':self.graph['snapshot'],'node':node},ensure_ascii=False,indent=2)+'\n'

    def guide(self):
        lines=[self.graph['scope'],'Snapshot: '+self.graph['snapshot']]
        for key in ['compile_fallback','const_input']:
            if key in self.nodes:lines += ['Summary ('+key+'): '+self.nodes[key]['claim']]
        for n in self.graph['nodes']:
            lines+=['',n['id']+': '+n['claim']]
            for e in n['evidence']:lines+=['factory_route/'+e['path']+':'+str(e['start'])+'-'+str(e['end']),e['quote']]
        lines+=['', 'Reviewed source edges:']+[e['source']+' --'+e['relation']+'--> '+e['target'] for e in self.graph['edges']]
        return '\n'.join(lines)+'\n'
