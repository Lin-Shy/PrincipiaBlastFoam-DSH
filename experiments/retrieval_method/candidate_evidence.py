"""混合召回、约束路径与不可拆分证据组；强无图模式不加载图。"""
from __future__ import annotations
from collections import defaultdict
import json
from pathlib import Path
import re
import time

from candidate_hybrid import Retriever,sha,wire,tokens
from candidate_graph import Paths,SEMANTIC


def scopes(query,cases):
    def literal(name):return re.search(r'(?<![A-Za-z_0-9/])'+re.escape(name)+r'(?![A-Za-z_0-9/])',query) is not None
    exact=[c for c in cases if literal(c) or literal(c.removeprefix('tutorials/'))]
    if exact:return {'status':'literal_path','cases':exact}
    candidates=[c for c in cases if literal(c.rsplit('/',1)[-1])]
    solvers={c.split('/')[1] for c in cases if len(c.split('/'))>2 and literal(c.split('/')[1])}
    if solvers:candidates=[c for c in candidates if c.split('/')[1] in solvers]
    return {'status':'ambiguous' if len(candidates)>1 else 'literal_name' if candidates else 'unrestricted','cases':candidates}


def merged_ranges(anchors):
    by_path=defaultdict(list)
    for a in anchors:
        by_path[a['path']].append((a['start'],a['end']))
    result=[]
    for path,ranges in sorted(by_path.items()):
        merged=[]
        for a,b in sorted(set(ranges)):
            if merged and a<=merged[-1][1]+1:merged[-1]=(merged[-1][0],max(b,merged[-1][1]))
            else:merged.append((a,b))
        result.extend({'path':path,'start':a,'end':b} for a,b in merged)
    return result


class Engine:
    def __init__(self,index,graph_path=None,*,semantic=True):
        begin=time.monotonic()
        self.retriever=Retriever(index,semantic=semantic)
        corpus=Path(self.retriever.manifest['corpus_root'])
        self.files={}
        for doc in self.retriever.docs:
            if doc['path'] not in self.files:
                raw=(corpus/doc['path']).read_bytes()
                if sha(raw)!=doc['source_sha256']:raise ValueError('candidate source drift')
                self.files[doc['path']]=raw.decode().splitlines()
        paths=set(self.files)
        self.cases=sorted({p.removesuffix('/system/controlDict') for p in paths if p.endswith('/system/controlDict')})
        self.graph=None;self.nodes={};self.by_file=defaultdict(list);self.adjacency=defaultdict(list)
        if graph_path:
            self.graph=json.loads(graph_path.read_text());self.nodes=self.graph['nodes'];self.paths=Paths(self.graph)
            if self.graph['corpus_id']!=self.retriever.manifest['corpus_id']:raise ValueError('graph/hybrid corpus mismatch')
            for nid,n in self.nodes.items():self.by_file[n['path']].append(nid)
            self.edges={e['id']:e for e in self.graph['edges']}
            for e in self.graph['edges']:self.adjacency[e['source']].append(e)
        self.initialization={'seconds':time.monotonic()-begin,'graph_loaded':self.graph is not None,
                             'source_files':len(self.files),'passages':len(self.retriever.docs),
                             'semantic_recall':semantic,'model_calls':0}

    def evidence(self,anchors):
        result=[]
        for a in merged_ranges(anchors):
            path,start,end=a['path'],a['start'],a['end']
            if path not in self.files or not 1<=start<=end<=len(self.files[path]):raise ValueError('candidate evidence out of corpus')
            raw='\n'.join(self.files[path][start-1:end])
            result.append({**a,'id':sha([self.retriever.manifest['corpus_id'],path,start,end])[:24],
                           'text':'\n'.join(f'{i}: {self.files[path][i-1]}' for i in range(start,end+1)),
                           'original_range_sha256':sha(raw.encode())})
        return result

    def context(self,nid):
        """Full physical identity and every ancestor header, including explicit local selectors."""
        n=self.nodes[nid];anchors=list(n['evidence']);visited=set();current=n
        while current.get('parent') in self.nodes and current['parent'] not in visited:
            parent=self.nodes[current['parent']];visited.add(parent['id']);anchors.extend(parent['evidence'])
            for sibling in self.by_file[n['path']]:
                s=self.nodes[sibling]
                key=s.get('key') or ''
                if s.get('parent')==parent['id'] and (key in {'type','enabled','active','activationModel','equationOfState','thermodynamics','transport'} or key.endswith('Model')):
                    anchors.extend(s['evidence'])
            current=parent
        return anchors

    def query(self,question,*,gap='',translation='',seen_groups=(),cap=6000,with_scope=True,with_cross=True,
              with_paths=True,with_groups=True,with_gap=True,semantic=True,slots=()):
        begin=time.monotonic()
        query='\n'.join(x for x in [question,translation,gap] if x)
        if len(query)>12000 or cap<1000:raise ValueError('invalid query or evidence budget')
        selected=scopes(query,self.cases) if with_scope else {'status':'scope_constraint_disabled','cases':[]}
        hits,recall_audit=self.retriever.query(query,case_scopes=selected['cases'],semantic=semantic)
        candidates=[];path_audit={'expanded_edges':0};query_terms=set(tokens(query))
        for hit in hits:
            candidates.append({'id':'passage:'+hit['id'],'kind':'raw_passage','score':hit['score'],
                               'anchors':[hit],'terms':set(tokens(hit['text'])),'metadata':{'path':hit['path']}})
        if self.graph is not None:
            seeds={}
            for hit in hits:
                for nid in self.by_file[hit['path']]:
                    n=self.nodes[nid]
                    if n['kind'] in {'file','directory','case_directory','source_span','script_directory'}:continue
                    if any(a['start']<=hit['end'] and a['end']>=hit['start'] for a in n['evidence']):
                        relevance=len(set(tokens(n.get('label','')+' '+(n.get('value') or '')))&query_terms)
                        seeds[nid]=max(seeds.get(nid,0),hit['score']+.004*min(relevance,8))
            seed_list=sorted(seeds.items(),key=lambda row:(-row[1],row[0]))[:32]
            found,path_audit=self.paths.search(seed_list,case_scopes=selected['cases'],with_paths=with_paths,with_cross=with_cross,with_scope=with_scope)
            for path in found:
                nid=path['node'];n=self.nodes[nid];edges=[self.edges[e['id']] for e in path['edges']]
                cross_edges=[e for e in edges if e.get('instance_evidence') and e.get('definition_evidence')]
                if cross_edges:
                    anchors=[];condition_text=[]
                    for e in cross_edges:
                        anchors.extend(self.context(e['source']));anchors.extend(e['definition_evidence'])
                        for rel in self.adjacency[e['target']]:
                            if rel['relation'] in SEMANTIC:
                                anchors.extend(rel['evidence']);condition_text.extend(rel.get('conditions',[]))
                    kind='cross_source_group'
                else:
                    anchors=self.context(nid) if n['kind']=='configuration' and with_paths else list(n['evidence'])
                    condition_text=[];kind='scoped_source_group'
                for e in edges:anchors.extend(e.get('evidence',[]))
                if not anchors:continue
                candidates.append({'id':'group:'+sha([path['nodes'],path['edges']])[:24], 'kind':kind,
                     'score':path['score'],'anchors':anchors,'terms':set(tokens(n['label'])),
                     'metadata':{'scope':n.get('scope'),'dictionary':n.get('dictionary'),'role':n.get('role'),
                                 'conditions':condition_text,'condition_satisfied':None,
                                 'path_relations':[{'relation':e['relation'],'status':e['status'],
                                                    'source':e['source'],'target':e['target'],
                                                    'traversal':path['edges'][i]['direction']} for i,e in enumerate(edges)]}})
        # Ablating grouping removes the combined cache as well as the group metadata.
        if not with_groups:
            flat={}
            for c in candidates:
                for a in c['anchors']:
                    k=sha([a['path'],a['start'],a['end']])[:24]
                    flat.setdefault(k,{'id':'ungrouped:'+k,'kind':'independent_span','score':c['score'],
                                      'anchors':[a],'terms':set(),'metadata':{}})
            candidates=list(flat.values())
        seen=set(seen_groups);candidates=[c for c in candidates if c['id'] not in seen]
        candidates.sort(key=lambda c:(-c['score'],c['id']))
        selected_groups=[];evidence={};sources={};covered=set();deferred=[]
        # Complete group packing: either every anchor and condition is present, or none is.
        while candidates:
            chosen=min(candidates,key=lambda c:(-(c['score']+.008*len((c['terms']&query_terms)-covered)),c['id']))
            candidates.remove(chosen)
            group_evidence=self.evidence(chosen['anchors'])
            trial_evidence={**evidence};trial_sources={**sources}
            for a in group_evidence:
                sid=sha(a['path'])[:16];trial_sources[sid]=a['path']
                trial_evidence[a['id']]={'source':sid,'start':a['start'],'end':a['end'],'text':a['text']}
            group={'id':chosen['id'],'kind':chosen['kind'],'evidence':[a['id'] for a in group_evidence],**chosen['metadata']}
            result={'status':'ok','scope':selected,'groups':selected_groups+[group],'sources':trial_sources,'evidence':trial_evidence,
                    'citation_rule':'Use sources mapping and exact numbered evidence. Conditions are declarations, not automatically satisfied.'}
            if with_gap:
                result['gaps']={'deferred_groups':len(deferred)+len(candidates),'requested_slots':list(slots),
                                'not_proven':'condition satisfaction, execution, and absence are not established by retrieval'}
            if len(wire(result))<=cap:
                selected_groups.append(group);evidence=trial_evidence;sources=trial_sources;covered|=chosen['terms']&query_terms
            else:deferred.append(chosen['id'])
        result={'status':'ok','scope':selected,'groups':selected_groups,'sources':sources,'evidence':evidence,
                'citation_rule':'Use sources mapping and exact numbered evidence. Conditions are declarations, not automatically satisfied.'}
        if with_gap:
            result['gaps']={'deferred_groups':len(deferred),'requested_slots':list(slots),
                            'not_proven':'condition satisfaction, execution, and absence are not established by retrieval'}
        if len(wire(result))>cap:raise ValueError('scope/slot metadata exceeds budget')
        return result,{'seconds':time.monotonic()-begin,'recall':recall_audit,'paths':path_audit,
                       'returned_group_ids':[g['id'] for g in selected_groups],'deferred_group_ids':deferred,
                       'graph_loaded':self.graph is not None,'with_scope':with_scope,'with_cross':with_cross,
                       'with_paths':with_paths,'with_groups':with_groups,'with_gap':with_gap,'semantic':semantic,
                       'returned_characters':len(wire(result))}
