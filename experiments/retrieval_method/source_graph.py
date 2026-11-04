"""来源图检索：对象定位、来源作用域、证据扩展与中文别名。"""

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


from collections import defaultdict
import re
import time

from candidate_graph_utils import tokens

PLATFORM_WORDS = {'blastfoam', 'openfoam'}
ENGLISH_STOP = {'a','an','the','of','to','and','in','for','is','on','with','as','from','or','if','it','this','that','be','by'}

# Source-supported semantic relations only. Physical containment is already
# available through source ownership; expanding it as relevance causes hubs.
RELATION_DECAY = {
    'DOCUMENTED_BY': .90, 'PARAMETER_CONTEXT': .90,
    'DESCRIBES': .85, 'PARAMETER_OF': .85,
    'REQUIRES': .85, 'CONFLICTS_WITH': .80,
    'SAME_PUBLIC_IDENTITY': .90, 'EXPLAINS': .80,
    'SELECTS_MODEL': .85, 'CONSUMES_FIELD': .70, 'PRODUCES_FIELD': .70,
    'SOURCE_SECTION_PARENT': .60,
    'FILE_SELECTOR_CONTEXT': .90,
}


class EvidenceGraph(KnowledgeGraphRetriever):
    def __init__(self, *args, evidence_policy='compact', **kwargs):
        if evidence_policy not in {'compact', 'whole'}:
            raise ValueError('Unknown original evidence policy')
        super().__init__(*args, **kwargs)
        self.evidence_policy = evidence_policy

    def _facet_flat(self, query):
        """Scan graph text for technical identifiers; no fitted term statistics.

        Platform names are scope context, not distinctive search identities.
        Complete identifiers carry twice the weight of their camel-case parts.
        Chinese aliases remain a separate matching channel, avoiding dilution
        of a precise parameter name by a long natural-language question.
        """
        distinctive = re.sub(r'(?<![A-Za-z0-9_])(?:blastfoam|openfoam)(?![A-Za-z0-9_])',' ',query,flags=re.I)
        identifiers = {v.casefold() for v in re.findall(r'[A-Za-z_][A-Za-z0-9_]*',distinctive)} - PLATFORM_WORDS - ENGLISH_STOP
        qt = set(tokens(distinctive)) - PLATFORM_WORDS - ENGLISH_STOP
        english = {t for t in qt if t.isascii()} | identifiers
        chinese = qt - english
        weights = {t: 2 if t in identifiers else 1 for t in english}
        cases = [p for p in self.cases if present(query,p.split('/')[-1]) or p in query]
        manual_only = '手册' in query and '教程' not in query and not cases
        tutorial_only = '只查教程' in query or '仅查教程' in query
        ranked, scanned, filtered, navigation = [], 0, 0, 0
        for nid,node in self.nodes.items():
            case = self.case_paths.get(node['path'])
            if ((cases and case and case not in cases) or
                (manual_only and node['path'].startswith('tutorials/')) or
                (tutorial_only and node['path'].startswith('manual/'))):
                filtered += 1
                continue
            if node.get('dictionary','').startswith('FoamFile'):
                continue
            unit = self.graph['units'][node['unit_id']]
            headings = [c['title'] for c in unit.get('context',[])]
            if any(re.fullmatch(r'(?:table of )?contents|目录',h.strip(),re.I) for h in headings):
                navigation += 1
                continue
            text = ' '.join(str(node.get(k) or '') for k in ('label','name','subject','owner_model','key','value','dictionary','body'))
            text += ' ' + ' '.join(node.get('aliases',[]))
            scanned += len(text)
            nt = set(tokens(text))
            context_terms = set(tokens(' '.join(headings)))
            hits = english & nt
            context_hits = english & context_terms
            cn = chinese & nt
            # Original relative paths help resolve explicit case/file context,
            # but a filename match alone cannot supply semantic answer content.
            path_match = bool(set(tokens(node['path'])) & identifiers)
            if not hits and not context_hits and not cn and not path_match:
                continue
            lexical = 30 * sum(weights[t] for t in hits)/max(1,sum(weights.values()))
            lexical += 8 * len(cn)/max(1,len(chinese))
            lexical += 8 * sum(weights[t] for t in context_hits)/max(1,sum(weights.values()))
            identity = str(node.get('name') or node.get('owner_model') or '').casefold()
            key = str(node.get('key') or '').casefold()
            score = lexical + 4 * bool(identity and identity in identifiers) + 4 * bool(key and key in identifiers)
            score += 2 * path_match + 4 * (case in cases if case else False)
            conditions = condition_text(node.get('conditions',[])) if self.options['with_conditions'] else ''
            condition_overlap = len(qt & set(tokens(conditions)))
            score += min(2,condition_overlap)
            ranked.append(dict(node_id=nid,score=score,origin=nid,visited=[nid],route=[],
                reasons=dict(technical_identifier_overlap=sorted(hits),chinese_overlap=len(cn),
                    source_heading_overlap=sorted(context_hits),
                    exact_identity_match=identity in identifiers,condition_overlap=condition_overlap)))
        ranked.sort(key=lambda r:(-r['score'],r['node_id']))
        return dict(items=ranked,diagnostic=dict(seeds=ranked[:self.options['seed_limit']],
            graph_field_characters_scanned=scanned,scope_filtered_nodes=filtered,
            navigation_only_nodes_excluded=navigation,
            external_index_loaded=False,model_calls=0,rank_is_before_character_budget=True,
            source_owners=len({n['owner'] for n in self.nodes.values()}),
            seed_policy='separate_technical_identifiers_and_chinese_aliases_v2'))

    def rank(self, query):
        started = time.monotonic()
        enabled = self.options['with_paths']
        flat = self._facet_flat(query)
        seeds = flat['diagnostic']['seeds']
        best = {r['node_id']: dict(r) for r in flat['items']}
        frontier = seeds
        expanded = 0
        qt = terms(query)
        cases = [p for p in self.cases if present(query, p.split('/')[-1]) or p in query]
        if enabled:
            for _ in range(self.options['depth']):
                following = []
                for row in frontier:
                    for target, edge, direction in self.adjacency[row['node_id']]:
                        decay = RELATION_DECAY.get(edge['relation'])
                        if decay is None or target in row['visited']:
                            continue
                        if edge['relation'] == 'FILE_SELECTOR_CONTEXT' and direction != 'forward':
                            continue
                        node = self.nodes[target]
                        # Flat rankings applied the scope policy. Nodes outside
                        # the native pool still need the same explicit filter.
                        case = case_directory(node['path'])
                        if cases and case and case not in cases:
                            continue
                        if '手册' in query and '教程' not in query and not cases and node['path'].startswith('tutorials/'):
                            continue
                        if ('只查教程' in query or '仅查教程' in query) and node['path'].startswith('manual/'):
                            continue
                        # A section's parent is structural context, not a license
                        # to traverse every sibling section of the whole manual.
                        if edge['relation'] == 'SOURCE_SECTION_PARENT':
                            if not qt & terms(' '.join(str(node.get(k) or '') for k in ('label', 'name', 'body'))):
                                continue
                        expanded += 1
                        score = row['score'] * decay
                        route = row['route'] + [{
                            'edge_id': edge['id'], 'relation': edge['relation'],
                            'direction': direction, 'cross_owner': edge['cross_owner'],
                            'conditions': edge.get('conditions', []), 'condition_evaluated': False,
                        }]
                        candidate = dict(node_id=target, score=score, origin=row['origin'],
                            visited=row['visited'] + [target], route=route,
                            reasons={'typed_route': True, 'decay': decay})
                        if target not in best or score > best[target]['score']:
                            best[target] = candidate
                            following.append(candidate)
                frontier = sorted(following, key=lambda r: (-r['score'], r['node_id']))[:self.options['seed_limit']]
        # Deduplicate source units BEFORE spending ranking slots on diversity.
        # This prevents many semantic nodes from one section occupying top-10.
        units = {}
        for row in best.values():
            uid = self.nodes[row['node_id']]['unit_id']
            if uid not in units or (row['score'], row['node_id']) > (units[uid]['score'], units[uid]['node_id']):
                units[uid] = row
        candidates = list(units.values())
        native, path_counts = [], defaultdict(int)
        while candidates and len(native) < self.options['native_limit']:
            row = min(candidates, key=lambda r: (-r['score'] / (1 + .25 * path_counts[self.nodes[r['node_id']]['path']]), r['node_id']))
            candidates.remove(row)
            node = self.nodes[row['node_id']]
            path_counts[node['path']] += 1
            native.append({**row, 'native_rank': len(native) + 1, 'path': node['path'],
                'owner': node['owner'], 'anchors': node['evidence'],
                'conditions': node.get('conditions', []) if self.options['with_conditions'] else []})
        return dict(schema='typed_evidence_graph_ranking_v2_development', items=native,
            options=dict(self.options), graph_sha256=self.graph_sha256,
            diagnostic={**flat['diagnostic'], 'seeds': seeds, 'expanded_edges': expanded,
                'graph_scan_seconds_and_ranking': time.monotonic() - started,
                'cross_owner_additive_bonus': 0, 'ranked_unique_source_units': len(units),
                'evidence_policy': self.evidence_policy})

    def read_native(self, ranking):
        if self.evidence_policy == 'whole':
            return super().read_native(ranking)
        items = []
        for row in ranking['items']:
            node = self.nodes[row['node_id']]
            unit = self.graph['units'][node['unit_id']]
            anchors = node['evidence']
            start = min(a['start'] for a in anchors)
            end = max(a['end'] for a in anchors)
            # Small original sections remain complete. Long units are centered
            # on the actual source quote, retaining four lines on both sides.
            # The agent can read the rest with the common read_source tool.
            if len(unit['text']) <= 1600:
                start, end = unit['start'], unit['end']
            else:
                start, end = max(unit['start'], start - 4), min(unit['end'], end + 4)
            items.append(dict(path=node['path'], ranges=[dict(start=start, end=end)],
                native_unit=row['node_id'], native_rank=row['native_rank'], owner=row['owner'],
                original_sha256=unit['sha256'], read_policy='source_quote_and_original_context',
                owning_original_fragment=dict(start=unit['start'], end=unit['end'])))
        return dict(items=items, ranking_diagnostic=ranking['diagnostic'], native_ranking=ranking)


from collections import defaultdict,deque
from pathlib import PurePosixPath
import re
import unicodedata

from candidate_graph_utils import tokens


def identity_fold(text):
    return ''.join(c for c in unicodedata.normalize('NFKD',text.casefold()) if not unicodedata.combining(c))


class SourceContextGraph(EvidenceGraph):
    def __init__(self,*args,context_characters=2400,identity_ranking=True,parent_retrieval=True,**kwargs):
        super().__init__(*args,**kwargs)
        if type(context_characters) is not int or context_characters<0:raise ValueError('Invalid source context budget')
        self.context_characters=context_characters
        self.identity_ranking=identity_ranking
        self.parent_retrieval=parent_retrieval
        self.raw_nodes={n['unit_id']:n['id'] for n in self.nodes.values() if n['kind']=='original_unit'}
        self.case_aliases=defaultdict(set)
        for unit in self.graph['units'].values():
            context=unit.get('source_context',{})
            if context.get('case_directory'):
                self.case_aliases[context['case_directory']].update(context['case_aliases'])
        for parent in self.graph.get('source_containers',{}).values():
            members=[self.graph['units'][uid] for uid in parent['members']]
            if (not members or len({u['id'] for u in members})!=len(members)
                or any(u['path']!=parent['path'] or u['sha256']!=parent['sha256'] for u in members)
                or members[0]['start']!=parent['start'] or members[-1]['end']!=parent['end']
                or any(l['end']+1!=r['start'] for l,r in zip(members,members[1:]))):
                raise ValueError('Invalid source parent membership')

    def _facet_flat(self,query):
        flat=super()._facet_flat(query)
        if not self.identity_ranking:return flat
        folded=identity_fold(query)
        if folded!=query.casefold():
            normalized=super()._facet_flat(folded)
            merged={r['node_id']:r for r in flat['items']}
            for row in normalized['items']:
                if row['node_id'] not in merged or row['score']>merged[row['node_id']]['score']:merged[row['node_id']]=row
            flat['items']=list(merged.values())
        distinctive=re.sub(r'(?<![A-Za-z0-9_])(?:blastfoam|openfoam)(?![A-Za-z0-9_])',' ',query,flags=re.I)
        distinctive=re.sub(r'场景\s*[A-Z](?![A-Za-z0-9_])',' ',distinctive)
        identifiers={identity_fold(s) for s in re.findall(r'[A-Za-z_\u00c0-\u024f][A-Za-z0-9_\u00c0-\u024f]*',distinctive)}-ENGLISH_STOP-PLATFORM_WORDS-{'yes','no','true','false'}
        explicit_files={p for p in self.hashes if any(p.casefold().endswith('/'+s.casefold()) for s in re.findall(r'[A-Za-z0-9_./]+',query) if '/' in s)}
        cases={case for case,aliases in self.case_aliases.items() if any(present(query,alias) for alias in aliases)}
        rows=[];node_by_unit=defaultdict(list)
        for row in flat['items']:node_by_unit[self.nodes[row['node_id']]['unit_id']].append(row)
        for uid,unit in self.graph['units'].items():
            if ('手册' in query and '教程' not in query and not cases and unit['path'].startswith('tutorials/')):continue
            if ('只查教程' in query or '仅查教程' in query) and unit['path'].startswith('manual/'):continue
            if re.search(r'"key"\s*:\s*"FoamFile"',unit['owner_key']):continue
            stripped=re.sub(r'/\*[\s\S]*?\*/|//[^\n]*','',unit['text']).strip()
            if not stripped:continue
            nodecase=unit.get('source_context',{}).get('case_directory')
            if cases and nodecase and nodecase not in cases:continue
            # Literal identity matching operates on each source-owned fragment,
            # so an exact filename/field anchors the owning original, rather
            # than rewarding an unrelated node with a common parameter name.
            text=identity_fold(unit['text'])
            exact={t for t in identifiers if present(text,t)}
            basename=PurePosixPath(unit['path']).name.casefold()
            filename=(basename in identifiers and (len(basename)>2 or bool(cases))) or unit['path'] in explicit_files
            context_match=bool(cases and nodecase in cases)
            declared=set(self.graph.get('source_file_declarations',{}).get(unit['path'],{}).get('keys',[]))
            joint_keys=identifiers & {identity_fold(k) for k in declared}
            joint_coverage=len(joint_keys)/max(1,len(identifiers)) if len(joint_keys)>=2 and self.options['with_cross'] and self.options['with_paths'] else 0
            headings=unit.get('context',[])
            direct_heading={t for t in identifiers if headings and headings[-1]['level']>1 and present(identity_fold(headings[-1]['title']),t)}
            if uid not in node_by_unit and (filename or context_match or direct_heading):
                nid=self.raw_nodes[uid]
                node_by_unit[uid]=[dict(node_id=nid,score=0,origin=nid,visited=[nid],route=[],reasons={})]
            for row in node_by_unit[uid]:
                node=self.nodes[row['node_id']]
                score=row['score']*.45+24*len(exact)/max(1,len(identifiers))
                score+=24*filename+12*context_match+12*joint_coverage
                score+=8*len(direct_heading)
                if '默认' in query and unit['path'].startswith('manual/') and present(text,'default'):score+=6
                if node.get('dictionary','').startswith('FoamFile'):continue
                reasons=dict(row['reasons'],source_filename_match=filename,
                    source_case_alias_match=context_match,original_identifier_overlap=sorted(exact),direct_heading_identifiers=sorted(direct_heading),parent_declared_key_overlap=sorted(joint_keys),parent_declaration_bonus=12*joint_coverage)
                rows.append({**row,'score':score,'reasons':reasons})
        rows.sort(key=lambda r:(-r['score'],self.nodes[r['node_id']]['path'],self.graph['units'][self.nodes[r['node_id']]['unit_id']]['start'],r['node_id']))
        return dict(items=rows,diagnostic={**flat['diagnostic'],'seeds':rows[:self.options['seed_limit']],
            'seed_policy':'literal_case_file_and_owned_original_v3','source_derived_cases':sorted(cases)})

    def rank(self,query):
        result=super().rank(query)
        result['schema']='source_identity_context_graph_ranking_v3_development'
        result['diagnostic'].update(context_characters=self.context_characters,identity_ranking=self.identity_ranking,parent_retrieval=self.parent_retrieval)
        return result

    def _context(self,row):
        node=self.nodes[row['node_id']];uid=node['unit_id'];unit=self.graph['units'][uid]
        selected={uid:unit};routes={uid:[]}
        if not self.options['with_paths'] or not self.context_characters:return selected,routes
        if self.parent_retrieval:
            parents=[self.graph['source_containers'][cid] for cid in unit.get('parent_context_ids',[])]
            parents.sort(key=lambda p:(p['characters'],p['start']))
            def bridge(source,target,parent):
                if source==target:return []
                for dest,edge,direction in self.adjacency[source]:
                    if dest==target and edge['relation']=='SOURCE_PARENT_CONTEXT' and edge.get('support',{}).get('container_id')==parent['id']:
                        return [dict(edge_id=edge['id'],relation=edge['relation'],direction=direction,cross_owner=edge['cross_owner'],container_id=parent['id'])]
                raise ValueError('Source parent membership lacks an allowed graph edge')
            # Preserve ancestor introductions before spending the context
            # allowance on sibling detail. A long parent is not silently
            # described as fully returned: every selected fragment is listed.
            for parent in parents:
                intro=self.graph['units'][parent['members'][0]]
                if intro['id'] in selected:continue
                if not self.options['with_cross'] and intro['owner']!=unit['owner']:continue
                if sum(len(v['text']) for v in selected.values())+len(intro['text'])>self.context_characters:continue
                selected[intro['id']]=intro
                routes[intro['id']]=bridge(self.raw_nodes[uid],self.raw_nodes[intro['id']],parent)
            for parent in parents:
                members=[self.graph['units'][v] for v in parent['members']]
                combined={**selected,**{v['id']:v for v in members}}
                if sum(len(v['text']) for v in combined.values())>self.context_characters:continue
                if not self.options['with_cross'] and any(v['owner']!=unit['owner'] for v in members):continue
                representative=self.raw_nodes[parent['members'][0]]
                for v in members:
                    selected[v['id']]=v
                    routes[v['id']]=bridge(self.raw_nodes[uid],representative,parent)+bridge(representative,self.raw_nodes[v['id']],parent) if v['id']!=uid else []
        used=sum(len(v['text']) for v in selected.values());frontier=deque([(self.raw_nodes[k],routes[k]) for k in selected])
        while frontier:
            current,route=frontier.popleft()
            for target,edge,direction in sorted(self.adjacency[current],key=lambda e:self.graph['units'][self.nodes[e[0]]['unit_id']]['start']):
                if edge['relation']!='SOURCE_NEXT_FRAGMENT':continue
                other=self.nodes[target];v=self.graph['units'][other['unit_id']]
                if v['id'] in selected or v['path']!=unit['path']:continue
                if any(c['title'].strip().casefold() in {'contents','table of contents','目录'} for c in v.get('context',[])):continue
                # File boilerplate is a traversal barrier, never a relevance hit.
                if re.search(r'"key"\s*:\s*"FoamFile"',v['owner_key']):continue
                if used+len(v['text'])>self.context_characters:continue
                used+=len(v['text']);selected[v['id']]=v
                next_route=route+[dict(edge_id=edge['id'],direction=direction,relation=edge['relation'],cross_owner=edge['cross_owner'])]
                routes[v['id']]=next_route;frontier.append((target,next_route))
        return selected,routes

    def read_native(self,ranking):
        items=[];seen=set()
        for row in ranking['items']:
            selected,routes=self._context(row)
            fresh=[v for k,v in selected.items() if k not in seen]
            if not fresh:continue
            fresh.sort(key=lambda v:v['start']);ranges=[]
            for unit in fresh:
                if ranges and ranges[-1]['end']+1==unit['start']:ranges[-1]['end']=unit['end']
                else:ranges.append(dict(start=unit['start'],end=unit['end']))
                seen.add(unit['id'])
            items.append(dict(path=row['path'],ranges=ranges,native_unit=row['node_id'],
                native_rank=row['native_rank'],owner=row['owner'],original_sha256=self.hashes[row['path']],
                read_policy='original_fragments_linked_by_literal_adjacency',
                context_fragments=[dict(unit_id=v['id'],owner=v['owner'],start=v['start'],end=v['end'],route=routes[v['id']]) for v in fresh]))
        return dict(items=items,ranking_diagnostic=ranking['diagnostic'],native_ranking=ranking)


from collections import defaultdict, deque
from pathlib import PurePosixPath
import re
import time
import unicodedata

from candidate_graph_utils import tokens


def query_identifiers(query):
    text = identity_fold(query)
    text = re.sub(r'(?<![A-Za-z0-9_])(?:blastfoam|openfoam)(?![A-Za-z0-9_])', ' ', text, flags=re.I)
    text = re.sub(r'场景\s*[a-z](?![A-Za-z0-9_])', ' ', text)
    return set(re.findall(r'[A-Za-z_][A-Za-z0-9_]*', text)) - ENGLISH_STOP - PLATFORM_WORDS - {'yes', 'no', 'true', 'false'}


def accent_fold(text):
    # Tokenization needs the original camel-case boundaries.
    return ''.join(c for c in unicodedata.normalize('NFKD', text) if not unicodedata.combining(c))


class _ForwardGraphScan(EvidenceGraph):
    """An alternative base scan for SourceContextGraph's identity rescoring.

    The multiple-inheritance order intentionally places this between the source
    identity layer and EvidenceGraph; it changes field preparation, not the
    graph-only retrieval boundary. Every query still scans every allowed node.
    """
    def _facet_flat(self, query):
        distinctive = accent_fold(query)
        distinctive = re.sub(r'(?<![A-Za-z0-9_])(?:blastfoam|openfoam)(?![A-Za-z0-9_])', ' ', distinctive, flags=re.I)
        distinctive = re.sub(r'场景\s*[a-z](?![A-Za-z0-9_])', ' ', distinctive, flags=re.I)
        identifiers = query_identifiers(query)
        qt = set(tokens(distinctive)) - PLATFORM_WORDS - ENGLISH_STOP
        english = {t for t in qt if t.isascii()} | identifiers
        chinese = qt - english
        weights = {t: 2 if t in identifiers else 1 for t in english}
        cases, manual_only, tutorial_only = self._scope(query)
        rows = []; scanned = filtered = navigation = 0
        for nid, fields in self._forward.items():
            node = self.nodes[nid]
            if not self._allowed(node, cases, manual_only, tutorial_only):
                filtered += 1; continue
            if fields['boilerplate']:continue
            if fields['navigation']:
                navigation += 1; continue
            scanned += fields['characters']
            nt = fields['terms']; headings = fields['heading_terms']
            hits = english & nt; context_hits = english & headings; cn = chinese & nt
            path_match = bool(fields['path_terms'] & identifiers)
            if not hits and not context_hits and not cn and not path_match:continue
            lexical = 30 * sum(weights[t] for t in hits) / max(1, sum(weights.values()))
            lexical += 8 * len(cn) / max(1, len(chinese))
            lexical += 8 * sum(weights[t] for t in context_hits) / max(1, sum(weights.values()))
            condition_overlap = len(qt & fields['condition_terms'])
            score = lexical + 4 * (bool(fields['identity']) and fields['identity'] in identifiers)
            score += 4 * (bool(fields['key']) and fields['key'] in identifiers)
            score += 2 * path_match + 4 * (fields['case'] in cases if fields['case'] else False)
            score += min(2, condition_overlap)
            rows.append(dict(node_id=nid, score=score, origin=nid, visited=[nid], route=[], reasons=dict(
                technical_identifier_overlap=sorted(hits), chinese_overlap=len(cn), source_heading_overlap=sorted(context_hits),
                exact_identity_match=fields['identity'] in identifiers, condition_overlap=condition_overlap)))
        rows.sort(key=lambda r: (-r['score'], r['node_id']))
        return dict(items=rows, diagnostic=dict(seeds=rows[:self.options['seed_limit']],
            graph_field_characters_scanned=scanned, scope_filtered_nodes=filtered, navigation_only_nodes_excluded=navigation,
            external_index_loaded=False, model_calls=0, rank_is_before_character_budget=True,
            forward_graph_fields_cached=True, query_or_result_cache=False,
            source_owners=len({n['owner'] for n in self.nodes.values()}), seed_policy='forward_graph_fields_v4'))


class AdaptiveSourceGraph(SourceContextGraph, _ForwardGraphScan):
    def __init__(self, *args, context_policy='adaptive', parent_ratio=.5, context_seed_limit=10, **kwargs):
        if context_policy not in {'adaptive', 'adjacent', 'blanket', 'none'}:
            raise ValueError('Unknown physical source context policy')
        if type(parent_ratio) not in (float, int) or not 0 <= parent_ratio < 1:
            raise ValueError('Parent threshold must be in [0,1)')
        if type(context_seed_limit) is not int or context_seed_limit < 1:
            raise ValueError('Positive context seed limit required')
        super().__init__(*args, **kwargs)
        self.context_policy = context_policy; self.parent_ratio = parent_ratio; self.context_seed_limit = context_seed_limit
        self._forward = {}
        for nid, node in self.nodes.items():
            unit = self.graph['units'][node['unit_id']]
            text = ' '.join(str(node.get(k) or '') for k in ('label', 'name', 'subject', 'owner_model', 'key', 'value', 'dictionary', 'body'))
            text += ' ' + ' '.join(node.get('aliases', []))
            headings = [c['title'] for c in unit.get('context', [])]
            self._forward[nid] = dict(terms=frozenset(tokens(accent_fold(text))),
                heading_terms=frozenset(tokens(accent_fold(' '.join(headings)))), path_terms=frozenset(tokens(node['path'])),
                identity=identity_fold(str(node.get('name') or node.get('owner_model') or '')),
                key=identity_fold(str(node.get('key') or '')), characters=len(text),
                condition_terms=frozenset(tokens(condition_text(node.get('conditions', [])))) if self.options['with_conditions'] else frozenset(),
                case=unit.get('source_context', {}).get('case_directory'), boilerplate=node.get('dictionary', '').startswith('FoamFile'),
                navigation=any(re.fullmatch(r'(?:table of )?contents|目录', h.strip(), re.I) for h in headings))

    def _scope(self, query):
        cases = {case for case, aliases in self.case_aliases.items() if any(present(query, alias) for alias in aliases)}
        return cases, '手册' in query and '教程' not in query and not cases, '只查教程' in query or '仅查教程' in query

    def _allowed(self, node, cases, manual_only, tutorial_only):
        path = node['path']; case = self.graph['units'][node['unit_id']].get('source_context', {}).get('case_directory')
        return not ((cases and case and case not in cases) or (manual_only and path.startswith('tutorials/'))
                    or (tutorial_only and path.startswith('manual/')))

    def _facet_flat(self, query):
        flat = super()._facet_flat(query)
        # V3 suppressed a static graph-field seed bonus in no-extension mode.
        # Preserve identical flat seeds when the edge traversal alone is off.
        if self.identity_ranking and self.options['with_cross'] and not self.options['with_paths']:
            count = max(1, len(query_identifiers(query)))
            for row in flat['items']:
                keys = row['reasons'].get('parent_declared_key_overlap', [])
                bonus = 12 * len(keys) / count if len(keys) >= 2 else 0
                row['score'] += bonus
                row['reasons']['parent_declaration_bonus'] = bonus
            flat['items'].sort(key=lambda r: (-r['score'], self.nodes[r['node_id']]['path'],
                self.graph['units'][self.nodes[r['node_id']]['unit_id']]['start'], r['node_id']))
            flat['diagnostic']['seeds'] = flat['items'][:self.options['seed_limit']]
        return flat

    def rank(self, query):
        started = time.monotonic(); flat = self._facet_flat(query); seeds = flat['diagnostic']['seeds']
        best = {r['node_id']: dict(r) for r in flat['items']}; frontier = seeds; expanded = 0
        cases, manual_only, tutorial_only = self._scope(query); qt = terms(query)
        if self.options['with_paths']:
            for _ in range(self.options['depth']):
                following = []
                for row in frontier:
                    for target, edge, direction in self.adjacency[row['node_id']]:
                        decay = RELATION_DECAY.get(edge['relation'])
                        if decay is None or target in row['visited']:continue
                        if edge['relation'] == 'FILE_SELECTOR_CONTEXT' and direction != 'forward':continue
                        node = self.nodes[target]
                        if not self._allowed(node, cases, manual_only, tutorial_only):continue
                        if edge['relation'] == 'SOURCE_SECTION_PARENT' and not qt & terms(' '.join(str(node.get(k) or '') for k in ('label', 'name', 'body'))):continue
                        expanded += 1; score = row['score'] * decay
                        route = row['route'] + [dict(edge_id=edge['id'], relation=edge['relation'], direction=direction,
                            cross_owner=edge['cross_owner'], conditions=edge.get('conditions', []), condition_evaluated=False)]
                        candidate = dict(node_id=target, score=score, origin=row['origin'], visited=row['visited'] + [target],
                            route=route, reasons=dict(typed_route=True, decay=decay))
                        if target not in best or score > best[target]['score']:
                            best[target] = candidate; following.append(candidate)
                frontier = sorted(following, key=lambda r: (-r['score'], r['node_id']))[:self.options['seed_limit']]
        units = {}
        for row in best.values():
            uid = self.nodes[row['node_id']]['unit_id']
            if uid not in units or (row['score'], row['node_id']) > (units[uid]['score'], units[uid]['node_id']):units[uid] = row
        candidates = list(units.values()); native = []; path_counts = defaultdict(int)
        while candidates and len(native) < self.options['native_limit']:
            row = min(candidates, key=lambda r: (-r['score'] / (1 + .25 * path_counts[self.nodes[r['node_id']]['path']]), r['node_id']))
            candidates.remove(row); node = self.nodes[row['node_id']]; path_counts[node['path']] += 1
            native.append({**row, 'native_rank': len(native) + 1, 'path': node['path'], 'owner': node['owner'],
                'anchors': node['evidence'], 'conditions': node.get('conditions', []) if self.options['with_conditions'] else []})
        return dict(schema='adaptive_source_context_graph_v4', items=native, options=dict(self.options), graph_sha256=self.graph_sha256,
            diagnostic={**flat['diagnostic'], 'expanded_edges': expanded, 'graph_scan_seconds_and_ranking': time.monotonic() - started,
                'cross_owner_additive_bonus': 0, 'ranked_unique_source_units': len(units), 'evidence_policy': 'owned_original_context',
                'context_policy': self.context_policy, 'context_characters': self.context_characters,
                'parent_ratio_strictly_greater_than': self.parent_ratio, 'context_seed_limit': self.context_seed_limit})

    def _bridge(self, source, target, parent):
        if source == target:return []
        for dest, edge, direction in self.adjacency[source]:
            if dest == target and edge['relation'] == 'SOURCE_PARENT_CONTEXT' and edge.get('support', {}).get('container_id') == parent['id']:
                return [dict(edge_id=edge['id'], relation=edge['relation'], direction=direction, cross_owner=edge['cross_owner'], container_id=parent['id'])]
        raise ValueError('Physical parent context lacks an allowed source-owned edge')

    def _select_context(self, row, hits):
        uid = self.nodes[row['node_id']]['unit_id']; unit = self.graph['units'][uid]
        selected = {uid: unit}; routes = {uid: []}; decisions = []
        if not self.options['with_paths'] or not self.context_characters or self.context_policy == 'none':return selected, routes, decisions
        if self.context_policy == 'blanket':
            selected, routes = super()._context(row)
            return selected, routes, [dict(policy='blanket_physical_parents_and_ancestor_introductions')]
        if self.context_policy == 'adaptive':
            parents = [self.graph['source_containers'][cid] for cid in unit.get('parent_context_ids', [])]
            for parent in sorted(parents, key=lambda p: (p['characters'], p['start'])):
                members = [self.graph['units'][k] for k in parent['members']]
                ratio = len(hits & set(parent['members'])) / len(members)
                eligible = len(members) > 1 and ratio > self.parent_ratio and parent['characters'] <= self.context_characters
                if not self.options['with_cross'] and any(v['owner'] != unit['owner'] for v in members):eligible = False
                decisions.append(dict(container_id=parent['id'], hit_fraction=ratio, members=len(members), eligible=eligible))
                if not eligible:continue
                representative = self.raw_nodes[parent['members'][0]]
                for v in members:
                    selected[v['id']] = v
                    routes[v['id']] = self._bridge(self.raw_nodes[uid], representative, parent) + self._bridge(representative, self.raw_nodes[v['id']], parent) if v['id'] != uid else []
                break
        used = sum(len(v['text']) for v in selected.values()); frontier = deque((self.raw_nodes[k], routes[k]) for k in selected)
        while frontier:
            current, route = frontier.popleft()
            for target, edge, direction in sorted(self.adjacency[current], key=lambda e: self.graph['units'][self.nodes[e[0]]['unit_id']]['start']):
                if edge['relation'] != 'SOURCE_NEXT_FRAGMENT':continue
                other = self.nodes[target]; v = self.graph['units'][other['unit_id']]
                if v['id'] in selected or v['path'] != unit['path'] or used + len(v['text']) > self.context_characters:continue
                if re.search(r'"key"\s*:\s*"FoamFile"', v['owner_key']):continue
                if any(c['title'].strip().casefold() in {'contents', 'table of contents', '目录'} for c in v.get('context', [])):continue
                used += len(v['text']); selected[v['id']] = v
                routes[v['id']] = route + [dict(edge_id=edge['id'], relation=edge['relation'], direction=direction, cross_owner=edge['cross_owner'])]
                frontier.append((target, routes[v['id']]))
        return selected, routes, decisions

    def read_native(self, ranking):
        hits = {self.nodes[r['node_id']]['unit_id'] for r in ranking['items'][:self.context_seed_limit]}
        items = []; seen = set()
        for row in ranking['items']:
            uid = self.nodes[row['node_id']]['unit_id']; selected, routes, decisions = self._select_context(row, hits)
            fresh = [v for k, v in selected.items() if k not in seen]
            if not fresh:continue
            # Always deliver the located fragment before surrounding material.
            fresh.sort(key=lambda v: (v['id'] != uid, v['start'])); ranges = []
            for v in fresh:
                if ranges and ranges[-1]['end'] + 1 == v['start']:ranges[-1]['end'] = v['end']
                else:ranges.append(dict(start=v['start'], end=v['end']))
                seen.add(v['id'])
            items.append(dict(path=row['path'], ranges=ranges, native_unit=row['node_id'], native_rank=row['native_rank'],
                owner=row['owner'], original_sha256=self.hashes[row['path']], read_policy='located_original_first_then_selected_physical_context',
                context_policy=self.context_policy, parent_decisions=decisions,
                context_fragments=[dict(unit_id=v['id'], owner=v['owner'], start=v['start'], end=v['end'], route=routes[v['id']]) for v in fresh]))
        return dict(items=items, ranking_diagnostic=ranking['diagnostic'], native_ranking=ranking)


from collections import defaultdict
import re
import time



class FocusedEvidenceGraph(AdaptiveSourceGraph):
    POLICIES = {'balanced', 'focused', 'ppr', 'ppr_focused', 'gated', 'compact', 'expanded', 'neutral', 'adaptive'}
    def __init__(self,*args,policy='balanced',**kwargs):
        if policy not in self.POLICIES:raise ValueError('Unknown focused graph policy')
        super().__init__(*args,**kwargs)
        self.policy=policy
        if policy in {'compact','adaptive'}:self.context_characters=1200
        if policy=='expanded':self.context_characters=4800
        self.unit_identity={uid:identity_fold(u['text']) for uid,u in self.graph['units'].items()}

    def _facet_flat(self,query):
        flat=super()._facet_flat(query)
        best={}
        for row in flat['items']:
            uid=self.nodes[row['node_id']]['unit_id']
            if uid not in best or row['score']>best[uid]['score']:best[uid]=row
        leaders=sorted(best.values(),key=lambda r:-r['score'])[:8]
        allowed_units={self.nodes[r['node_id']]['unit_id']:r for r in leaders}
        by_node={r['node_id']:r for r in flat['items']}
        ids=query_identifiers(query)
        cases,manual_only,tutorial_only=self._scope(query)
        for source,neighbors in self.adjacency.items():
            uid=self.nodes[source]['unit_id']
            if uid not in allowed_units:continue
            for target,edge,direction in neighbors:
                if edge['relation']!='LITERAL_HEADING_REFERENCE' or direction!='forward':continue
                if not self._allowed(self.nodes[target],cases,manual_only,tutorial_only):continue
                source_row=allowed_units[uid]
                # An explicit selector key gates the documentation lookup.
                # Otherwise retain a bounded low-priority reference candidate.
                key=str(edge.get('support',{}).get('selector_key','')).casefold()
                value=source_row['score']*(.88 if key in ids else .65)
                if target not in by_node or value>by_node[target]['score']:
                    by_node[target]=dict(node_id=target,score=value,origin=source_row['origin'],visited=[source,target],
                        route=[dict(edge_id=edge['id'],relation=edge['relation'],direction=direction,
                            cross_owner=edge['cross_owner'],condition_evaluated=False)],
                        reasons=dict(literal_documentation_lookup=True,selector_key=key))
        flat['items']=sorted(by_node.values(),key=lambda r:(-r['score'],r['node_id']))
        flat['diagnostic']['seeds']=flat['items'][:self.options['seed_limit']]
        return flat

    def _propagate(self, flat, query):
        """Normalized walk on allowed typed graph edges; source anchors retained."""
        seeds=flat['diagnostic']['seeds'];total=sum(max(0,r['score']) for r in seeds)
        if total<=0:return {},0
        restart={r['node_id']:max(0,r['score'])/total for r in seeds}
        mass=restart.copy();visits=defaultdict(float);expanded=0
        cases,manual_only,tutorial_only=self._scope(query)
        for _ in range(3):
            nxt=defaultdict(float)
            for node,value in mass.items():
                neighbors=[]
                for target,edge,direction in self.adjacency[node]:
                    weight=RELATION_DECAY.get(edge['relation'])
                    if weight is None:continue
                    if edge['relation']=='FILE_SELECTOR_CONTEXT' and direction!='forward':continue
                    if not self._allowed(self.nodes[target],cases,manual_only,tutorial_only):continue
                    neighbors.append((target,weight))
                denom=sum(w for _,w in neighbors)
                if denom:
                    for target,weight in neighbors:
                        nxt[target]+=.65*value*weight/denom;expanded+=1
            for node,value in restart.items():nxt[node]+=.35*value
            mass=dict(nxt)
            for node,value in mass.items():visits[node]+=value/3
        unit_mass=defaultdict(float)
        for nid,value in visits.items():unit_mass[self.nodes[nid]['unit_id']]+=value
        return unit_mass,expanded

    def rank(self,query):
        started=time.monotonic()
        previous=super().rank(query)
        ids=query_identifiers(query)
        pool=[]
        for row in previous['items']:
            uid=self.nodes[row['node_id']]['unit_id'];u=self.graph['units'][uid]
            hits={word for word in ids if present(self.unit_identity[uid],word)}
            headings=u.get('context',[])
            scope=(u['path'],headings[-1]['line'] if headings else u['owner'])
            pool.append({**row,'facet_hits':hits,'scope_key':scope})
        propagation={};edges=0
        if self.policy.startswith('ppr'):
            propagation,edges=self._propagate(self._facet_flat(query),query)
        max_mass=max(propagation.values(),default=1)
        selected=[];seen_facets=set();path_counts=defaultdict(int);scope_counts=defaultdict(int)
        while pool and len(selected)<self.options['native_limit']:
            def priority(row):
                uid=self.nodes[row['node_id']]['unit_id']
                if self.policy=='neutral':return row['score']
                novel=len(row['facet_hits']-seen_facets)/max(1,len(ids))
                value=row['score']*(1+.35*novel)
                if propagation:value+=8*propagation.get(uid,0)/max_mass
                # Diversity within one logical section matters more than
                # spreading unrelated hits over many physical files.
                return value/(1+.03*path_counts[row['path']]+.12*scope_counts[row['scope_key']])
            row=min(pool,key=lambda r:(-priority(r),r['path'],self.graph['units'][self.nodes[r['node_id']]['unit_id']]['start']))
            pool.remove(row);row['selection_score']=priority(row)
            path_counts[row['path']]+=1;scope_counts[row['scope_key']]+=1;seen_facets|=row['facet_hits']
            row['facet_hits']=sorted(row['facet_hits']);row['scope_key']=list(row['scope_key'])
            selected.append({**row,'native_rank':len(selected)+1})
        result={**previous,'schema':'focused_evidence_graph_v5','items':selected}
        result['diagnostic']={**previous['diagnostic'],'v5_policy':self.policy,'degree_normalized_walk_edges':edges,
            'graph_scan_seconds_and_ranking':time.monotonic()-started,'external_index_loaded':False,
            'query_or_gold_specific_weights':False,'question_or_result_cache':False,
            'public_query_identifiers':sorted(ids)}
        return result

    def read_for_budget(self,ranking,characters):
        if type(characters) is not int or characters<1:raise ValueError('Positive source delivery budget required')
        old=self.context_characters
        self.context_characters=min(2400,max(1200,characters//5))
        try:return self.read_native(ranking)
        finally:self.context_characters=old

    def read_native(self,ranking):
        if self.policy=='gated':
            ids=set(ranking['diagnostic']['public_query_identifiers'])
            hits={self.nodes[r['node_id']]['unit_id'] for r in ranking['items'][:self.context_seed_limit]}
            seen=set();items=[]
            for row in ranking['items']:
                uid=self.nodes[row['node_id']]['unit_id'];unit=self.graph['units'][uid]
                selected,routes,decisions=self._select_context(row,hits)
                heading=unit.get('context',[])
                ancestors={v['line'] for v in heading}
                fresh=[]
                for k,v in selected.items():
                    same_heading=v.get('context',[])==heading
                    explicit=any(present(self.unit_identity[k],word) for word in ids)
                    introduction=v['start'] in ancestors
                    if k not in seen and (k==uid or same_heading or explicit or introduction):fresh.append(v)
                if not fresh:continue
                fresh.sort(key=lambda v:(v['id']!=uid,v['start']))
                ranges=[]
                for v in fresh:
                    if ranges and ranges[-1]['end']+1==v['start']:ranges[-1]['end']=v['end']
                    else:ranges.append(dict(start=v['start'],end=v['end']))
                    seen.add(v['id'])
                items.append(dict(path=row['path'],ranges=ranges,native_unit=row['node_id'],native_rank=row['native_rank'],
                    owner=row['owner'],original_sha256=self.hashes[row['path']],read_policy='query_gated_original_context',
                    context_fragments=[dict(unit_id=v['id'],start=v['start'],end=v['end'],route=routes[v['id']]) for v in fresh]))
            return dict(items=items,ranking_diagnostic=ranking['diagnostic'],native_ranking=ranking)
        if not self.policy.endswith('focused'):return super().read_native(ranking)
        # Gated physical context: retain a located fragment's immediate
        # continuation, then allocate further context to other ranked anchors.
        old=self.context_seed_limit
        self.context_seed_limit=5
        try:return super().read_native(ranking)
        finally:self.context_seed_limit=old


from collections import defaultdict
import re

from candidate_graph_utils import tokens


def chinese_terms(text):
    return {t for t in tokens(text) if not t.isascii()}


def alias_relevance(query, query_terms, aliases):
    """Forward fields only; short generic Chinese overlap has no bonus."""
    best = 0.
    for alias in aliases:
        words = chinese_terms(alias)
        overlap = words & query_terms
        if not words or not overlap:
            continue
        exact = bool(re.search(r'[\u4e00-\u9fff]{3,}', alias)) and alias in query
        # Two adjacent bigrams (at least three characters) or an exact phrase
        # are needed; the evidence need not repeat a long question verbatim.
        if exact:
            best = 1.
        elif len(overlap) >= 2:
            coverage = len(overlap)/len(words)
            if coverage >= .5:
                best = max(best, .7*coverage)
    return best


class BilingualScopeGraph(FocusedEvidenceGraph):
    def __init__(self, *args, semantic_policy='unit', **kwargs):
        if semantic_policy not in {'unit', 'case'}:
            raise ValueError('Unknown source alias policy')
        super().__init__(*args, policy='adaptive', **kwargs)
        self.semantic_policy = semantic_policy
        self.source_aliases = {}
        self.case_source_aliases = defaultdict(set)
        for node in self.nodes.values():
            if node['kind'] != 'original_unit' or not node.get('alias_grounding'):
                continue
            self.source_aliases[node['unit_id']] = tuple(node.get('aliases', []))
            unit = self.graph['units'][node['unit_id']]
            case = unit.get('source_context', {}).get('case_directory')
            if case and unit['path'].lower().endswith('/readme.md'):
                self.case_source_aliases[case].update(node.get('aliases', []))

    def _facet_flat(self, query):
        flat = super()._facet_flat(query)
        query_terms = chinese_terms(query)
        semantic = {uid:alias_relevance(query, query_terms, aliases)
            for uid, aliases in self.source_aliases.items()}
        explicit_cases, _, _ = self._scope(query)
        cases = {}
        if self.semantic_policy == 'case' and not explicit_cases:
            cases = {case:alias_relevance(query, query_terms, aliases)
                for case, aliases in self.case_source_aliases.items()}
        for row in flat['items']:
            unit = self.graph['units'][self.nodes[row['node_id']]['unit_id']]
            own = semantic.get(unit['id'], 0)
            scope = cases.get(unit.get('source_context', {}).get('case_directory'), 0)
            row['score'] += 8*own + 8*scope
            row['reasons']['source_alias_bonus'] = 8*own
            row['reasons']['soft_case_source_alias_bonus'] = 8*scope
        flat['items'].sort(key=lambda r:(-r['score'], r['node_id']))
        flat['diagnostic']['seeds'] = flat['items'][:self.options['seed_limit']]
        flat['diagnostic'].update(bilingual_policy=self.semantic_policy,
            semantic_case_scope='soft prior, no inferred alias can exclude a case',
            source_owned_alias_units=len(self.source_aliases))
        return flat

