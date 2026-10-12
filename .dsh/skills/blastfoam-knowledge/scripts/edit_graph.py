"""Source-backed dictionary scopes and model-to-coefficient navigation for case edits.

Relations identify edit context, not supported physics or a runnable configuration.
"""
from collections import defaultdict, Counter
from pathlib import Path
import argparse
import json
import math
import re
import evidence_bundle as b
import cpp_inputs


def builder_digest():
    return b.sha(Path(__file__).read_bytes()+Path(cpp_inputs.__file__).read_bytes())


def identifier_words(name):
    """Keep dictionary identity while exposing camel-case names to prose queries."""
    return re.sub(r'([a-z0-9])([A-Z])',r'\1 \2',name).replace('_',' ').split()


def model_intent_text(text):
    """Exclude preservation/removal spans from model *recall*, not the task.

    The full request still ranks existing edit scopes and reaches the removal
    binder. This narrow grammar never changes or generates an edit operation.
    """
    return re.sub(r'(?:删除|删去|移除|保留|保持|\b(?:remove|delete|keep|preserve|leave)\b)[^;；。\n]*',
                  ' ',text,flags=re.I)


def edit_intent_text(text):
    keep=r'保留|保持|不改动|不修改|不要修改|不改变|\b(?:keep|preserve|leave|do not change|unchanged)\b'
    edit=r'改为|换为|切换|修改|设置为|设为|赋值|采用|删除|移除|不再保留|\b(?:change|set|switch|replace|remove|delete|use)\b|[A-Za-z_]\w*\s*[=:：]'
    parts=re.split(r'([;；。\n])',text)
    for i,part in enumerate(parts):
        match=re.search(keep,part,re.I)
        if not match:continue
        # Postposed preservation ("air ... 保持原样") binds its subject too.
        # If the same clause first specifies an edit, retain that prefix.
        parts[i]=part[:match.start()] if re.search(edit,part[:match.start()],re.I) else ' '
    return ''.join(parts)


def input_requirements(node):
    result={}
    for item in node['entries']:
        key=item['key'];kind=item['requirement']
        if kind=='required':result.setdefault('required',[]).append(key)
        elif kind=='optional':result.setdefault('optional',{})[key]=item['default_expression']
        else:result.setdefault('conditional',{})[key]=item.get('conditions',[])
    return result


def literal_input_schema(source, header):
    """Recognize only the direct readCoeff/subDict scalar constructor idiom.

    This is bounded syntactic evidence, not a general C++ parser or a complete
    inherited schema. Comments cannot supply names or coefficient calls.
    """
    def uncomment(text):
        return re.sub(r'"(?:\\.|[^"\\])*"|//[^\n]*|/\*[\s\S]*?\*/',
            lambda m: m.group() if m.group().startswith('"') else re.sub(r'[^\n]',' ',m.group()),text)
    clean=uncomment(source);h=uncomment(header)
    models=re.findall(r'static\s+word\s+typeName\(\)\s*\{\s*return\s+"(\w+)<"\s*\+\s*Thermo::typeName\(\)',h)
    helpers=list(re.finditer(r'Foam::(\w+)<Thermo>::readCoeff\s*\(\s*const word& coeffName,\s*const dictionary& dict\s*\)\s*\{\s*(return\s+dict\.subDict\("(\w+)"\)\.lookup<scalar>\(coeffName\);)\s*\}',clean))
    if len(models)!=1 or len(helpers)!=1:return None
    helper=helpers[0];cls=helper.group(1)
    if not re.search(r'\bclass\s+'+re.escape(cls)+r'\b',h):return None
    constructor=re.search(r'Foam::'+re.escape(cls)+r'<Thermo>::'+re.escape(cls)+r'\(const dictionary& dict\)\s*:\s*([^{}#]*)\{\s*\}',clean)
    if not constructor:return None
    reads=list(re.finditer(r'\w+_\(readCoeff\("(\w+)", dict\)\)',constructor.group(1)))
    if not reads:return None
    line=lambda offset:source.count('\n',0,offset)+1
    start=line(constructor.start(1)+reads[0].start());end=line(constructor.start(1)+reads[-1].end())
    return {'model':models[0],'dictionary':helper.group(3),'keys':list(dict.fromkeys(m.group(1) for m in reads)),
            'start':start,'end':end,'dictionary_source':{'start':line(helper.start(2)),'end':line(helper.end(2)),
                'text':source[helper.start(2):helper.end(2)]}}


def build(engine):
    original=b.k.read_json(b.k.release_path(engine.skill/'index')/'graph.json')
    nodes={};groups=defaultdict(list);edges=[];mapping={}
    for n in original['nodes']:
        if n['kind']=='configuration' and not n['dictionary_path'].startswith('FoamFile/'):
            groups[n['evidence']['path'],n['dictionary_path'].rpartition('/')[0]].append(n)
    for (path,parent),entries in sorted(groups.items()):
        uid=b.sha([path,parent])[:20]
        owner=next((c for c in engine.graph['cases'] if path.startswith(c+'/')),None)
        if owner is None:continue
        start=min(n['line_start'] for n in entries);end=max(n['line_end'] for n in entries)
        nodes[uid]={'id':uid,'kind':'dictionary_scope','path':path,'case':owner,'scope':parent,
                    'start':start,'end':end,'entries':[{'entry':n['dictionary_path'],'value':n['value'],
                    'start':n['line_start'],'end':n['line_end']} for n in entries]}
        for n in entries:mapping[n['id']]=uid
    byscope={(n['path'],n['scope']):uid for uid,n in nodes.items()}
    def link(a,z,relation,status,**identity):
        if a!=z:edges.append({'source':a,'target':z,'relation':relation,'status':status,**identity})
    for uid,n in list(nodes.items()):
        # Exact dictionary nesting, never cross-phase or cross-case.
        parent=n['scope'].rpartition('/')[0]
        if n['scope'] and (n['path'],parent) in byscope:
            link(uid,byscope[n['path'],parent],'PARENT_DICTIONARY','structural_context')
        if n['scope'].split('/')[-1]=='thermoType':
            for e in n['entries']:
                key=e['entry'].split('/')[-1]
                coefficient={'thermo':'thermodynamics'}.get(key,key)
                target='/'.join(x for x in [parent,coefficient] if x)
                if (n['path'],target) in byscope:
                    link(uid,byscope[n['path'],target],'SELECTOR_COEFFICIENTS','co_located_schema_candidate',selector_entry=e['entry'])
    # Preserve exact existing name/scope matches to manual definitions.
    outgoing=defaultdict(list)
    for e in original['edges']:outgoing[e['source']].append(e)
    onodes={n['id']:n for n in original['nodes']}
    for e in original['edges']:
        if e['relation']!='REFERS_TO_DEFINITION' or e['source'] not in mapping:continue
        for page in outgoing[e['target']]:
            if page['relation']!='DOCUMENTED_ON':continue
            ev=page['evidence'];uid=b.sha([ev['path'],ev['line_start'],ev['line_end']])[:20]
            nodes.setdefault(uid,{'id':uid,'kind':'manual','path':ev['path'],'case':None,
                'scope':onodes[e['target']].get('title',''),'start':ev['line_start'],'end':ev['line_end'],'entries':[]})
            link(mapping[e['source']],uid,'DOCUMENTED_MODEL',e['status'],selector_entry=onodes[e['source']]['dictionary_path'])
    # Scope aggregation must not merge transport/thermo/EOS identities. Join only
    # the same exact selector entry to its own coefficient group and definition.
    coefficient_edges=[e for e in edges if e['relation']=='SELECTOR_COEFFICIENTS']
    for documented in list(edges):
        if documented['relation']!='DOCUMENTED_MODEL':continue
        for coefficient in coefficient_edges:
            if (coefficient['source'],coefficient['selector_entry'])==(documented['source'],documented['selector_entry']):
                link(coefficient['target'],documented['target'],'DOCUMENTED_COEFFICIENTS',
                     'selector_scoped_definition_not_physical_compatibility',selector_entry=coefficient['selector_entry'])
    # Alternatives are limited to the explicitly documented model's own section family.
    # They are candidates for inspection, never assertions of interchangeable physics.
    families=defaultdict(list)
    for n in onodes.values():
        if n['kind']=='manual_section' and len(n.get('hierarchy',[]))>1:
            families[n['evidence']['path'],tuple(n['hierarchy'][:-1])].append(n)
    for e in original['edges']:
        if e['relation']!='REFERS_TO_DEFINITION' or e['source'] not in mapping:continue
        ref=onodes[e['target']]
        if ref['kind']!='manual_section':continue
        for option in families[ref['evidence']['path'],tuple(ref['hierarchy'][:-1])]:
            if option['id']==ref['id']:continue
            ev=option['evidence'];uid=b.sha([ev['path'],ev['line_start'],ev['line_end']])[:20]
            nodes.setdefault(uid,{'id':uid,'kind':'manual','path':ev['path'],'case':None,
                'scope':option['title'],'start':ev['line_start'],'end':ev['line_end'],'entries':[]})
            link(mapping[e['source']],uid,'MODEL_FAMILY_OPTION','same_manual_family_not_compatibility',
                 selector_entry=onodes[e['source']]['dictionary_path'])
    # Constructor evidence is global, selector and coefficient instances remain
    # case-scoped. A symbolic base forwarding is not a specialized input schema.
    source_diagnostics=[]
    provenance_path='manual/source_code/provenance.json'
    source_versions={}
    if provenance_path in engine.graph['inventory']:
        provenance_bytes=(engine.skill/'corpus'/provenance_path).read_bytes()
        if b.sha(provenance_bytes)!=engine.graph['inventory'][provenance_path]:raise ValueError('source provenance changed')
        for item in json.loads(provenance_bytes):
            name='manual/source_code/'+item['repository']+'/'+item['path']
            if name in engine.graph['inventory']:
                if item['sha256']!=engine.graph['inventory'][name]:raise ValueError('source provenance digest mismatch')
                source_versions[name]={'repository':item['repository'],'commit':item['commit']}
    for path in sorted(engine.graph['inventory']):
        header=str(Path(path).with_suffix('.H'))
        if not path.startswith('manual/source_code/') or not path.endswith('.C') or header not in engine.graph['inventory']:continue
        analysis=cpp_inputs.analyze(''.join(engine.texts[path]),''.join(engine.texts[header]))
        constructors=[m for m in analysis['models'] if m['dictionary_only_constructor']]
        source_diagnostics.append({'path':path,'diagnostics':analysis['diagnostics'],
            'constructors':len(analysis['models']),'dictionary_only_constructors':len(constructors),
            'unresolved':[u for m in constructors for u in m['unresolved']]})
        if len(constructors)!=1:continue
        schema=constructors[0]
        dictionaries=sorted({f['dictionary'] for f in schema['inputs'] if f['dictionary']})
        for dictionary in dictionaries:
            facts=[f for f in schema['inputs'] if f['dictionary']==dictionary]
            uid=b.sha([path,'input_schema',dictionary,schema])[:20]
            reads=[ev for f in facts for ev in f['evidence']]
            start=min(f['evidence'][0]['start'] for f in facts);end=max(f['evidence'][0]['end'] for f in facts)
            proof=next((ev for ev in reads if 'subDict' in ev['text']),reads[0])
            provenance={'source_sha256':engine.graph['inventory'][path],
                        'source_version':source_versions.get(path,{'status':'unversioned_fixture'}),
                        'model_source':header,'model_source_sha256':engine.graph['inventory'][header],
                        'evidence_status':'static_syntax','runtime_status':'not_evaluated'}
            nodes[uid]={'id':uid,'kind':'input_schema','path':path,'case':None,
                'scope':schema['model']+'/'+dictionary,'start':start,'end':end,'model':schema['model'],
                'dictionary_source':proof,'entries':[],**provenance,
                'complete_local_reads':schema['complete_local_reads'],
                'unresolved':schema['unresolved'],'dictionary_forwarding':schema['dictionary_forwarding']}
            parameter_ids={f['dictionary']+'/'+f['key']:b.sha([uid,f['dictionary'],f['key']])[:20] for f in facts}
            for fact in facts:
                entry=dictionary+'/'+fact['key'];pid=parameter_ids[entry];ev=fact['evidence'][0]
                nodes[pid]={'id':pid,'kind':'input_parameter','path':path,'case':None,
                    'scope':schema['model']+'/'+entry,'start':ev['start'],'end':ev['end'],
                    'entries':[],**provenance,**fact}
                nodes[uid]['entries'].append({'entry':entry,'parameter_node':pid,**fact})
                relation={'required':'READS_PARAMETER','optional':'READS_WITH_DEFAULT','conditional':'READS_WHEN'}[fact['requirement']]
                link(uid,pid,relation,'static_syntax')
                if 'default_expression' in fact:
                    did=b.sha([pid,'default',fact['default_expression']])[:20]
                    nodes[did]={'id':did,'kind':'default_expression','path':path,'case':None,
                        'scope':schema['model']+'/'+entry+'/default','start':ev['start'],'end':ev['end'],
                        'entries':[],**provenance,'expression':fact['default_expression'],
                        'unresolved_symbols':fact['unresolved_default_symbols']}
                    link(pid,did,'DEFAULTS_TO_EXPRESSION','not_evaluated')
                    for dependency in fact['default_dependencies']:
                        if dependency in parameter_ids:link(did,parameter_ids[dependency],'DEPENDS_ON_INPUT','static_member_binding')
            for forwarding in schema['dictionary_forwarding']:
                fid=b.sha([uid,'forwarding',forwarding])[:20];ev=forwarding['evidence']
                nodes[fid]={'id':fid,'kind':'dictionary_forwarding','path':path,'case':None,
                    'scope':schema['model']+'/'+forwarding['callee'],'start':ev['start'],'end':ev['end'],
                    'entries':[],**provenance,**forwarding}
                link(uid,fid,'FORWARDS_DICTIONARY','specialization_unresolved')
            manuals=[n['id'] for n in nodes.values() if n['kind']=='manual' and
                     re.sub(r'^\d+(?:\.\d+)*\s*','',n['scope']).strip(' `').lower()==schema['model'].lower()]
            for manual in manuals:
                relevant=[edge for edge in edges if edge['target']==manual
                    and edge['relation'] in ('MODEL_FAMILY_OPTION','DOCUMENTED_MODEL')
                    and (dictionary not in ('transport','thermodynamics','equationOfState','specie') or
                         any(c['source']==edge['source'] and c['selector_entry']==edge['selector_entry']
                             and nodes[c['target']]['scope'].rsplit('/',1)[-1]==dictionary for c in coefficient_edges))]
                if not relevant:continue
                link(manual,uid,'READS_COEFFICIENTS','static_syntax')
                for edge in relevant:
                    link(edge['source'],uid,'MODEL_INPUT_SCHEMA','static_syntax',selector_entry=edge['selector_entry'],via_model=manual)
    result={'version':'edit-graph-v5','builder_sha256':builder_digest(),
            'base_snapshot':engine.graph['snapshot'],'nodes':list(nodes.values()),
            'edges':list({b.wire(e):e for e in edges}.values()),'construction_api_tokens':0,
            'source_diagnostics':source_diagnostics}
    result['snapshot']=b.sha(result)
    return result


class EditSearch:
    def __init__(self,engine,graph=None):
        self.engine=engine;self.graph=graph or build(engine)
        g=self.graph
        if g['builder_sha256']!=builder_digest() or g['base_snapshot']!=engine.graph['snapshot']:
            raise ValueError('edit graph source/builder changed')
        if b.sha({k:v for k,v in g.items() if k!='snapshot'})!=g['snapshot']:raise ValueError('edit graph digest mismatch')
        self.nodes={n['id']:n for n in g['nodes']};self.adj=defaultdict(list)
        for e in g['edges']:
            self.adj[e['source']].append((e['target'],e,'forward'))
            self.adj[e['target']].append((e['source'],e,'reverse'))
        self.terms={uid:Counter(b.k.tokens(n['path']+' '+n['scope']+' '+self.raw(n))) for uid,n in self.nodes.items()}
        self.component_counts=Counter((n['case'],part) for n in self.nodes.values() if n['case'] is not None for part in n['scope'].split('/'))
        self.df=Counter(t for tf in self.terms.values() for t in tf)
        self.avg=sum(sum(tf.values()) for tf in self.terms.values())/max(1,len(self.terms))

    def raw(self,n):return ''.join(self.engine.texts[n['path']][n['start']-1:n['end']])

    def locate(self,original,case,query='',translation='',budget=5000,graph=True):
        if not isinstance(original,str) or not original.strip():raise ValueError('original task required')
        if type(budget)!=int or not 1000<=budget<=24000:raise ValueError('budget must be 1000..24000')
        if any(not isinstance(x,str) or len(x)>32768 for x in [original,query,translation]):raise ValueError('invalid query')
        case='tutorials/'+case.removeprefix('tutorials/')
        case=self.engine.graph['aliases'].get(case,case)
        if case not in self.engine.graph['cases']:raise ValueError('unknown case')
        self.engine.validate()
        q=self.engine.query_terms(edit_intent_text(original+'\n'+query+'\n'+translation))
        scores={}
        for uid,tf in self.terms.items():
            n=self.nodes[uid]
            if n['case']!=case:continue
            length=sum(tf.values());score=0
            for t,w in q.items():
                if tf[t]:score+=w*math.log(1+(len(self.nodes)-self.df[t]+.5)/(self.df[t]+.5))*tf[t]*2.2/(tf[t]+1.2*(.25+.75*length/self.avg))
            scope_tokens=set(b.k.tokens(n['scope']))
            score+=6*sum(w for t,w in q.items() if t in scope_tokens)
            scores[uid]=score
        # Literal scope/entry anchors outrank incidental comments in another phase.
        # Definition text supplies natural-language meaning for terse keys such as
        # mu/Pr, through selector-specific graph edges rather than guessed aliases.
        combined=edit_intent_text(original+'\n'+query+'\n'+translation)
        explicit=set(b.k.tokens(combined))
        manual_scores={}
        # Multiple literal constructor keys can identify a candidate without its
        # model name. A single shared key never supplies this shortcut.
        input_hints=set()
        input_text=model_intent_text(combined)
        named_inputs=set()
        if graph:
            for uid,n in self.nodes.items():
                if n['kind']!='input_schema':continue
                keys={e['entry'].split('/')[-1] for e in n['entries']}
                matched={key for key in keys if len(key)>=2 and re.search(
                    r'(?<![A-Za-z0-9_])'+re.escape(key)+r'\s*[=:：]\s*[+-]?(?:\d|\.\d)',input_text)}
                model=n.get('model','')
                named=bool(model) and re.search(r'(?<![A-Za-z0-9_])'+re.escape(model)+r'(?![A-Za-z0-9_])',input_text,re.I)
                if named:named_inputs.add(uid)
                if len(matched)>=2 or named:input_hints.add(uid)
            # Identical key signatures (ePower/hPower, for example) cannot
            # override an explicitly named model. Without one keep ambiguity.
            if named_inputs:input_hints=named_inputs
        hinted_selectors={(e['source'],e['selector_entry']) for e in self.graph['edges']
                          if e['relation']=='MODEL_INPUT_SCHEMA' and e['target'] in input_hints}
        hinted_pairs=[(e['source'],e['target']) for e in self.graph['edges']
                      if e['relation']=='SELECTOR_COEFFICIENTS' and (e['source'],e['selector_entry']) in hinted_selectors]
        for source,target in hinted_pairs:
            for uid in (source,target):
                if uid in scores:scores[uid]+=30
        if graph:
            for uid,tf in self.terms.items():
                if self.nodes[uid]['kind']!='manual':continue
                manual_scores[uid]=sum(math.log(1+(len(self.nodes)-self.df[t]+.5)/(self.df[t]+.5))
                    for t in explicit if len(t)>=3 and tf[t] and self.df[t]<=len(self.nodes)*.1)
            for edge in self.graph['edges']:
                if edge['relation']=='DOCUMENTED_COEFFICIENTS' and edge['source'] in scores:
                    scores[edge['source']]+=6*manual_scores.get(edge['target'],0)
        def explicit_target(uid):
            n=self.nodes[uid]
            def named(name):
                return len(name)>=2 and re.search(r'(?<![A-Za-z0-9_])'+re.escape(name)+r'(?![A-Za-z0-9_])',combined,re.I) is not None
            if n['scope'] and named(n['scope'].split('/')[0]):return 2
            for component in n['scope'].split('/'):
                words=identifier_words(component)
                # Match the whole compound name, not a generic suffix such as
                # "probes" that could refer to another function object.
                if len(words)>1 and re.search(r'(?<![A-Za-z0-9_])'+r'[\s_-]+'.join(re.escape(w[:-1])+'s?' if len(w)>3 and w.lower().endswith('s') and not w.lower().endswith('ss') else re.escape(w) for w in words)+r'(?![A-Za-z0-9_])',combined,re.I):
                    return 3 if self.component_counts[n['case'],component]==1 else 1
            if any(named(e['entry'].split('/')[-1]) for e in n['entries']):
                return 1 if n['scope'] else 2
            return 0
        ranked=sorted((u for u in scores if scores[u]>0),key=lambda u:(-explicit_target(u),-scores[u],u))
        # A second scope should cover explicitly requested keys that the first
        # scope cannot answer, before another high-scoring nearby dictionary.
        # This does not infer new keys or decide which edits are physically valid.
        def entry_anchors(uid):
            names={e['entry'].split('/')[-1] for e in self.nodes[uid]['entries']}
            return {name for name in names if len(name)>=2 and re.search(
                r'(?<![A-Za-z0-9_])'+re.escape(name)+r'(?![A-Za-z0-9_])',combined,re.I)}
        if len(ranked)>2:
            covered=entry_anchors(ranked[0])
            second=max(ranked[1:],key=lambda u:len(entry_anchors(u)-covered))
            if entry_anchors(second)-covered:
                ranked.remove(second);ranked.insert(1,second)
        candidate_packet=None
        # Candidate discovery is opt-in through a request for alternatives. This
        # keeps ordinary coefficient edits from becoming model-change proposals.
        if graph and ranked and re.search(r'\b(candidates?|alternatives?|options?)\b|候选|可选',combined,re.I):
            pairs=[e for e in self.graph['edges'] if e['relation']=='SELECTOR_COEFFICIENTS' and ranked[0] in (e['source'],e['target'])]
            groups=[]
            for pair in pairs:
                options=[]
                for edge in self.graph['edges']:
                    if edge['relation']!='MODEL_FAMILY_OPTION' or (edge['source'],edge['selector_entry'])!=(pair['source'],pair['selector_entry']):continue
                    n=self.nodes[edge['target']];tf=Counter(b.k.tokens(self.raw(n)))
                    matched=sorted(t for t in explicit if len(t)>=3 and tf[t] and self.df[t]<=max(3,len(self.nodes)*.1))
                    if len(matched)<2:continue
                    options.append({'model':re.sub(r'^\d+(?:\.\d+)*\s*','',n['scope']).strip(' `'),
                        'path':n['path'],'start':n['start'],'end':n['end'],'matched_terms':matched})
                options=sorted(options,key=lambda x:(x['path'],x['start'],x['model']))
                if len(options)>=2:groups.append((pair,options))
            if groups:
                pair,options=max(groups,key=lambda item:sum(len(x['matched_terms']) for x in item[1]))
                paths={x['path'] for x in options}
                proposal={'selector_entry':pair['selector_entry'],'status':'unselected; relevance is not compatibility',
                          'options':[{k:v for k,v in x.items() if k!='matched_terms' and (k!='path' or len(paths)>1)} for x in options]}
                if len(paths)==1:proposal['source_path']=next(iter(paths))
                if len(b.wire(proposal))<budget-1000:
                    candidate_packet=proposal
                    hinted_pairs.append((pair['source'],pair['target']))
        if graph and ranked:
            partners={z if a==ranked[0] else a for a,z in hinted_pairs if ranked[0] in (a,z)}
            partners={u for u in partners if u in ranked}
            if partners:
                second=max(partners,key=lambda u:scores[u])
                ranked.remove(second);ranked.insert(1,second)
        result={'status':'ok' if ranked else 'no_match','snapshot':self.graph['snapshot'],'case':case,
            'locations':[],'relations':[],'limits':'Exact dictionary paths identify edit scope. Relations are context, not proof of compatibility. Original task is retained.'}
        if candidate_packet:result['model_candidates']=candidate_packet
        selected=set()
        combined=edit_intent_text(original+'\n'+query+'\n'+translation)
        def requested_manual(uid):
            n=self.nodes[uid]
            if uid in input_hints:return True
            if n['kind'] not in ('manual','input_schema'):return False
            label=n.get('model') or re.sub(r'^\d+(?:\.\d+)*\s*','',n['scope']).strip(' `')
            return len(label)>=3 and re.search(r'(?<![A-Za-z0-9_])'+re.escape(label)+r'(?![A-Za-z0-9_])',input_text,re.I) is not None
        def add(uid,reason,reserve=0):
            if uid in selected:return True
            n=self.nodes[uid];raw=self.raw(n)
            item={'id':uid,'path':n['path'],'dictionary':n['scope'],'start':n['start'],'end':n['end'],
                'reason':reason,'entries':[e['entry'] for e in n['entries']],
                'text':raw[:1500],'complete':len(raw)<=1500}
            if n['kind']=='input_schema':
                item['dictionary_source']=n['dictionary_source']
                item['schema_scope']='Static local reads; inherited inputs unresolved; runtime unverified.'
                item['input_requirements']=input_requirements(n)
                item['complete_local_reads']=n['complete_local_reads']
                item['dictionary_forwarding']=[{'callee':f['callee'],'dictionary':f['dictionary'],
                    'line':f['evidence']['start']} for f in n['dictionary_forwarding']]
            candidate={**result,'locations':result['locations']+[item]}
            if len(b.wire(candidate))>budget-reserve:
                # Retain a useful ranked location even when its full scope is
                # large. The prefix remains verbatim and explicitly incomplete.
                item['complete']=False;item['text']=''
                if len(b.wire(candidate))>budget-reserve:return False
                lo=0;hi=min(len(raw),1500)
                while lo<hi:
                    mid=(lo+hi+1)//2;item['text']=raw[:mid]
                    if len(b.wire(candidate))<=budget-reserve:lo=mid
                    else:hi=mid-1
                item['text']=raw[:lo]
                if raw and not item['text']:return False
            result.update(candidate);selected.add(uid);return True
        # Same two initial scopes for both ablations; related scopes compete with later roots.
        for uid in ranked[:2]:add(uid,'query_match')
        if graph:
            frontier=sorted(selected,key=lambda u:(-scores.get(u,0),u))
            for hop in range(2):
                added=[]
                for uid in frontier:
                    candidates=sorted(self.adj[uid],key=lambda x:(not requested_manual(x[0]),x[1]['relation']!='MODEL_INPUT_SCHEMA',x[1]['relation']!='SELECTOR_COEFFICIENTS',-scores.get(x[0],0),x[0]))
                    for dst,e,direction in candidates:
                        if len(result['relations'])>=4:break
                        if dst in selected:continue
                        n=self.nodes[dst]
                        if n['case'] not in (case,None):continue
                        if e['relation']=='PARENT_DICTIONARY':continue
                        if n['kind'] in ('manual','input_schema'):
                            if not requested_manual(dst):continue
                        elif scores.get(dst,0)<=0:continue
                        old=list(result['locations']);prior=set(selected)
                        relation={**e,'traversal':direction}
                        if not add(dst,'linked_scope',len(b.wire(relation))+1):continue
                        candidate={**result,'relations':result['relations']+[relation]}
                        if len(b.wire(candidate))<=budget:
                            result.update(candidate);added.append(dst)
                        else:result['locations']=old;selected.clear();selected.update(prior)
                frontier=[u for u in added if self.nodes[u]['kind']!='manual']
        for uid in ranked[2:]:
            if len(selected)>=6:break
            add(uid,'query_match')
        return result


def main():
    p=argparse.ArgumentParser();p.add_argument('--original',required=True);p.add_argument('--case',required=True)
    p.add_argument('--query',default='');p.add_argument('--translation',default='');p.add_argument('--budget',type=int,default=5000)
    p.add_argument('--text-only',action='store_true');a=p.parse_args()
    e=EditSearch(b.EvidenceSearch())
    print(b.wire(e.locate(a.original,a.case,a.query,a.translation,a.budget,not a.text_only)))

if __name__=='__main__':main()
