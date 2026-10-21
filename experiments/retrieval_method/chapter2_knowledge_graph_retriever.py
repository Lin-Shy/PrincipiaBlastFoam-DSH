"""Direct graph scans and bounded source-owned traversal, with three ablations.

No BM25, embeddings, inverted index, fitted passage model or query cache.
Only original source anchors leave the ranking adapter for the QA agent.
"""
from collections import defaultdict
import copy
import hashlib
import json
from pathlib import Path,PurePosixPath
import re
import time

DEFAULTS={'with_cross':True,'with_conditions':True,'with_paths':True,
          'seed_limit':32,'native_limit':64,'depth':3,'allow_partial_development':False}
CONDITION_RELATIONS={'REQUIRES','CONFLICTS_WITH','VALID_FOR','HAS_LIMITATION'}

def terms(text):
    text=str(text).casefold()
    result=set(re.findall(r'[a-z_][a-z0-9_]*|\d+(?:\.\d+)*',text))
    for chunk in re.findall(r'[\u3400-\u9fff]+',text):
        result.update(chunk[i:i+2] for i in range(len(chunk)-1))
        if len(chunk)==1:result.add(chunk)
    return result

def literals(text):
    return set(re.findall(r'[A-Za-z_][A-Za-z0-9_./<>+-]*',text))

def present(text,name):
    return bool(re.search(r'(?<![A-Za-z0-9_])'+re.escape(name)+r'(?![A-Za-z0-9_])',text,re.I))

def condition_text(rows):
    return ' '.join(v if isinstance(v,str) else v.get('text','') for v in rows)

def case_directory(path):
    parts=PurePosixPath(path).parts
    if not parts or parts[0]!='tutorials':return None
    for i,p in enumerate(parts):
        if p in {'system','constant','0','0.orig','0.org'} and i>=3:return '/'.join(parts[:i])
    if parts[-1] in {'README.md','Allrun','Allclean','Allrun.parallel'}:return '/'.join(parts[:-1])
    return None

class KnowledgeGraphRetriever:
    def __init__(self,graph_path,corpus,options=None,corpus_manifest=None):
        started=time.monotonic();raw=Path(graph_path).read_bytes();self.graph_sha256=hashlib.sha256(raw).hexdigest()
        self.graph=json.loads(raw);self.root=Path(corpus).resolve();self.nodes=self.graph['nodes']
        self.options={**DEFAULTS,**(options or {})}
        if set(self.options)!=set(DEFAULTS):raise ValueError('unknown knowledge graph option')
        for name in ('with_cross','with_conditions','with_paths','allow_partial_development'):
            if type(self.options[name]) is not bool:raise ValueError('graph ablation requires explicit boolean')
        for name in ('seed_limit','native_limit','depth'):
            if type(self.options[name]) is not int or self.options[name]<1:raise ValueError('positive graph limits required')
        variant=self.graph.get('graph_variant')
        if variant is not None:
            expected={'with_cross':variant!='no_cross','with_conditions':variant!='no_conditions','with_paths':variant!='no_extension'}
            if variant not in {'full','no_cross','no_conditions','no_extension'} or any(self.options[k]!=v for k,v in expected.items()):
                raise ValueError('graph artifact and declared ablation disagree')
        if self.graph.get('schema')!='independent_verified_knowledge_graph_v1':raise ValueError('fresh independent verified graph required')
        if not self.graph.get('semantic_processing_complete') and not self.options['allow_partial_development']:
            raise ValueError('partial graph requires explicit development-only flag')
        if not self.options['with_conditions']:
            self.nodes=copy.deepcopy(self.nodes)
            for node in self.nodes.values():node.pop('conditions',None)
        self.hashes=self.graph['source_hashes']
        if corpus_manifest is None:raise ValueError('independent authority source map required')
        if json.loads(Path(corpus_manifest).read_text(encoding='utf-8'))['files']!=self.hashes:
            raise ValueError('graph authority differs from production corpus')
        units=self.graph['units']
        for path in self.hashes:self.source_lines(path)
        for nid,node in self.nodes.items():
            unit=units[node['unit_id']]
            if node['id']!=nid or node['owner']!=unit['owner'] or node['path']!=unit['path']:
                raise ValueError('unowned or shared graph node')
            if unit['sha256']!=self.hashes[unit['path']]:raise ValueError('source unit authority drift')
            for ev in node['evidence']:
                if ev['path']!=unit['path'] or ev['sha256']!=unit['sha256'] or not unit['start']<=ev['start']<=ev['end']<=unit['end']:
                    raise ValueError('node evidence crosses original source unit')
        self.adjacency=defaultdict(list)
        for e in self.graph['edges']:
            a,b=self.nodes[e['source']],self.nodes[e['target']]
            cross=a['owner']!=b['owner']
            if e['cross_owner']!=cross:raise ValueError('incorrect owner boundary label')
            # ALL owner boundaries are blocked, including physical nesting and
            # links within a single file. No unowned entity bridge is permitted.
            if cross and not self.options['with_cross']:continue
            if not self.options['with_conditions']:
                if e['relation'] in CONDITION_RELATIONS:continue
                e={k:v for k,v in e.items() if k!='conditions'}
            self.adjacency[e['source']].append((e['target'],e,'forward'))
            self.adjacency[e['target']].append((e['source'],e,'reverse'))
        self.case_paths={p:case_directory(p) for p in self.hashes}
        self.cases=sorted({v for v in self.case_paths.values() if v})
        self.load_seconds=time.monotonic()-started

    def source_lines(self,path):
        if path not in self.hashes or PurePosixPath(path).is_absolute() or '..' in PurePosixPath(path).parts:
            raise ValueError('original graph path outside corpus')
        target=(self.root/path).resolve()
        if not target.is_relative_to(self.root):raise ValueError('original graph path escapes corpus')
        raw=target.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=self.hashes[path]:raise ValueError('original graph source changed')
        return raw.decode('utf-8').splitlines()

    def rank(self,query):
        started=time.monotonic();qt=terms(query);explicit=literals(query)
        pieces={p.casefold() for v in explicit for p in v.split('/')}
        requested_fields={v.casefold() for v in explicit if '/' in v and not v.startswith(('manual/','tutorials/'))}
        cases=[p for p in self.cases if present(query,PurePosixPath(p).name) or p in query]
        manual_only=('手册' in query and '教程' not in query and not cases)
        tutorial_only=('只查教程' in query or '仅查教程' in query)
        requested_paths={p for p in self.hashes if any(p.casefold()==v.casefold() or p.casefold().endswith('/'+v.casefold()) for v in explicit if '/' in v)}
        def allowed(n):
            path=n['path'];case=self.case_paths.get(path)
            return not ((cases and case and case not in cases) or (manual_only and path.startswith('tutorials/')) or
                        (tutorial_only and path.startswith('manual/')))
        ranked=[];scanned=0;filtered=0
        for nid,n in self.nodes.items():
            if not allowed(n):filtered+=1;continue
            if n.get('dictionary','').startswith('FoamFile'):continue
            # Role, signatures and identity selector dictionaries are not
            # searched as a hidden channel for applicability conditions.
            text=' '.join(str(n.get(k) or '') for k in ('label','name','subject','owner_model','key','value','dictionary','body'))
            text+=' '+' '.join(n.get('aliases',[]))
            scanned+=len(text);nt=terms(text);overlap=len(qt&nt)
            field=n.get('dictionary','').casefold();key=n.get('key','').casefold()
            full=bool(field and field in requested_fields);key_match=bool(key and key in pieces)
            filename=n['path'] in requested_paths or PurePosixPath(n['path']).name.casefold() in pieces
            model_name=n.get('name',n.get('owner_model')) or (n.get('value') if n.get('selector_role') else None)
            model_match=bool(model_name and str(model_name).casefold() in pieces)
            if not (overlap or full or key_match or filename or model_match):continue
            lexical=12*overlap/max(1,len(qt))+4*overlap/max(1,len(nt))
            cond=condition_text(n.get('conditions',[])) if self.options['with_conditions'] else ''
            condition_overlap=len(qt&terms(cond))
            score=lexical+30*full+16*key_match+24*filename+20*model_match+min(4,condition_overlap)
            if self.case_paths.get(n['path']) in cases:score+=8
            if n['kind'] in {'domain_definition','domain_fact','configuration'}:score+=1
            ranked.append({'node_id':nid,'score':score,'origin':nid,'visited':[nid],'route':[],
              'reasons':{'lexical_overlap':overlap,'full_dictionary_match':full,'key_match':key_match,
                'filename_match':filename,'model_match':model_match,'condition_overlap':condition_overlap}})
        ranked.sort(key=lambda r:(-r['score'],r['node_id']));seeds=ranked[:self.options['seed_limit']]
        best={r['node_id']:r for r in ranked};frontier=seeds;expanded=0
        if self.options['with_paths']:
            for depth in range(self.options['depth']):
                following=[]
                for row in frontier:
                    for target,e,direction in self.adjacency[row['node_id']]:
                        if target in row['visited'] or not allowed(self.nodes[target]):continue
                        expanded+=1
                        conditions=e.get('conditions',[]) if self.options['with_conditions'] else []
                        bonus=min(3,len(qt&terms(condition_text(conditions))))
                        score=row['score']*.82+(5 if e['cross_owner'] else 1)+bonus
                        route=row['route']+[{'edge_id':e['id'],'relation':e['relation'],'direction':direction,
                          'cross_owner':e['cross_owner'],'conditions':conditions,'condition_evaluated':False}]
                        item={'node_id':target,'score':score,'origin':row['origin'],'visited':row['visited']+[target],
                              'route':route,'reasons':{'graph_route':True}}
                        if target not in best or score>best[target]['score']:
                            best[target]=item;following.append(item)
                following.sort(key=lambda r:(-r['score'],r['node_id']));frontier=following[:self.options['seed_limit']]
        # Fixed path diversity is shared by full and all ablations. Evidence
        # character truncation happens exclusively in the common source tools.
        candidates=list(best.values());native=[];path_counts=defaultdict(int)
        while candidates and len(native)<self.options['native_limit']:
            choice=min(candidates,key=lambda r:(-r['score']/(1+.25*path_counts[self.nodes[r['node_id']]['path']]),r['node_id']))
            candidates.remove(choice);node=self.nodes[choice['node_id']];path_counts[node['path']]+=1
            native.append({**choice,'native_rank':len(native)+1,'path':node['path'],'owner':node['owner'],
              'anchors':node['evidence'],'conditions':node.get('conditions',[]) if self.options['with_conditions'] else []})
        return {'schema':'source_owned_unbudgeted_graph_ranking_v1','items':native,'options':self.options,
          'graph_sha256':self.graph_sha256,'diagnostic':{'graph_scan_seconds_and_ranking':time.monotonic()-started,
            'graph_field_characters_scanned':scanned,'seeds':seeds,'expanded_edges':expanded,
            'scope_filtered_nodes':filtered,'external_index_loaded':False,'model_calls':0,
            'rank_is_before_character_budget':True,'source_owners':len({n['owner'] for n in self.nodes.values()})}}

    def read_native(self,ranking):
        items=[];seen=set()
        for row in ranking['items']:
            node=self.nodes[row['node_id']];unit=self.graph['units'][node['unit_id']]
            # Deliver the owning original fragment, so a short identifying
            # quote cannot hide its model definition or applicability clauses.
            # This never appends another owner's context or generated text.
            anchors=[{'path':unit['path'],'start':unit['start'],'end':unit['end'],'sha256':unit['sha256']}]
            for ev in anchors:
                key=(ev['path'],ev['start'],ev['end'])
                if key in seen:continue
                seen.add(key);lines=self.source_lines(ev['path'])
                if not 1<=ev['start']<=ev['end']<=len(lines):raise ValueError('invalid graph original evidence span')
                items.append({'path':ev['path'],'ranges':[{'start':ev['start'],'end':ev['end']}],
                  'native_unit':row['node_id'],'native_rank':row['native_rank'],'owner':row['owner'],
                  'original_sha256':ev['sha256'],'read_policy':'complete_owning_original_fragment'})
        return {'items':items,'ranking_diagnostic':ranking['diagnostic'],'native_ranking':ranking}

    def owner_boundary_audit(self):
        visited=set();components=[]
        for nid in self.nodes:
            if nid in visited:continue
            queue=[nid];owners=set();size=0
            while queue:
                current=queue.pop()
                if current in visited:continue
                visited.add(current);size+=1;owners.add(self.nodes[current]['owner'])
                queue.extend(target for target,e,d in self.adjacency[current] if target not in visited)
            components.append((size,len(owners)))
        return {'components':len(components),'maximum_owners_per_component':max((n for size,n in components),default=0),
                'nodes':len(visited),'cross_owner_edges_retained':sum(e['cross_owner'] for rows in self.adjacency.values() for target,e,d in rows)//2}
