"""Self-contained, evidence-backed blastFoam graph and retrieval. Python 3.11+."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import shutil
import tempfile

VERSION = '1.1'
ROOT = Path(__file__).resolve().parents[1]


def digest(data):
    return hashlib.sha256(data).hexdigest()


def encoded(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encoded(value))


def confined(root, relative):
    p = (root / relative).resolve()
    if not p.is_relative_to(root.resolve()):
        raise ValueError(f'path outside root: {relative}')
    return p


def tokens(text):
    text = text.replace('ﬁ', 'fi').replace('ﬂ', 'fl').replace('ﬀ', 'ff')
    # Preserve full identifiers and additionally split camelCase.
    words = re.findall(r'[A-Za-z][A-Za-z0-9_+]*', text)
    parts = re.sub(r'([a-z])([A-Z])', r'\1 \2', text)
    words += re.findall(r'[A-Za-z][A-Za-z0-9_+]*', parts)
    for run in re.findall(r'[\u4e00-\u9fff]+', text):
        words += [run[i:i+2] for i in range(len(run)-1)]
    stop = {'the','a','an','of','to','in','and','is','this','for','with','it','be','as','on','by','or','from'}
    return [w.lower() for w in words if w.lower() not in stop]


def lex(text):
    pattern = r'//[^\n]*|/\*[\s\S]*?\*/|#\{[\s\S]*?#\}|"(?:\\.|[^"\\])*"|[{}();\[\]]|[^\s{}();\[\]]+'
    result = []
    for match in re.finditer(pattern, text):
        token = match.group()
        if token.startswith(('//', '/*')):
            continue
        result.append((token, match.start(), match.end()))
    return result


def parse_dictionary(text):
    """Conservative structural parser; retains expressions, never evaluates directives."""
    ts = lex(text)
    entries, diagnostics = [], []

    def walk(i, parents, nested=False):
        occurrences = Counter()
        while i < len(ts):
            key, start, end = ts[i]
            if key == '}':
                return i + 1
            if key in (';', ')', '('):
                i += 1
                continue
            if key.startswith('#'):
                line = text.count('\n', 0, start)
                i += 1
                while i < len(ts) and text.count('\n', 0, ts[i][1]) == line:
                    i += 1
                diagnostics.append({'line': line+1, 'reason': 'directive_preserved', 'token': key})
                continue
            # OpenFOAM keys such as div(phi,U) and reconstruct(rho) are
            # unquoted function-shaped words, not a key followed by a list.
            if i + 1 < len(ts) and ts[i+1][0] == '(' and ts[i+1][1] == end:
                j = i + 1
                depth = 0
                while j < len(ts):
                    token, pos, finish = ts[j]
                    if token == '(':
                        depth += 1
                    elif token == ')':
                        depth -= 1
                        if depth == 0:
                            key = text[start:finish]
                            end = finish
                            i = j
                            break
                    elif token in (';', '{', '}'):
                        break
                    j += 1
            key = key.strip('"')
            occurrences[key] += 1
            component = key + (f'@{occurrences[key]}' if occurrences[key] > 1 else '')
            path = parents + [component]
            i += 1
            if i < len(ts) and ts[i][0] == '{':
                i = walk(i+1, path, True)
                continue
            value_start = ts[i][1] if i < len(ts) else end
            depth = 0
            end_pos = end
            terminated = False
            while i < len(ts):
                token, pos, finish = ts[i]
                if token == '}' and depth == 0:
                    break
                if token == ';' and depth == 0:
                    end_pos = finish
                    i += 1
                    terminated = True
                    break
                if token in ('(', '[', '{'):
                    depth += 1
                elif token in (')', ']', '}'):
                    depth -= 1
                end_pos = finish
                i += 1
            if terminated:
                raw = text[value_start:end_pos-1].strip()
                entries.append({'key':key, 'dictionary_path':'/'.join(path), 'value':raw,
                                'line_start':text.count('\n',0,start)+1,
                                'line_end':text.count('\n',0,end_pos)+1,
                                'resolved':not bool(re.search(r'[$#]',raw))})
            else:
                diagnostics.append({'line':text.count('\n',0,start)+1,'reason':'unterminated_or_non_dictionary','token':key})
        if nested:
            diagnostics.append({'line': len(text.splitlines()), 'reason':'unclosed_dictionary'})
        return i

    walk(0, [])
    return entries, diagnostics


def dictionary_like(relative, text):
    name = Path(relative).name
    return 'FoamFile' in text[:2000] or name.endswith('Dict') or name.endswith('Properties')


def literal_dictionary_includes(corpus, inventory, active_paths):
    """Discover dictionary fragments by literal include reachability, not suffix.

    Comments, code blocks, environment expansions and includeEtc are never
    evaluated. Physical fragment paths remain distinct from the including
    dictionary's effective scope; an include is not a runtime success claim.
    """
    texts = {}
    for path in active_paths:
        try:
            text = confined(corpus, path).read_bytes().decode('utf-8')
        except UnicodeError:
            continue
        if '\x00' not in text:
            texts[path] = text
    roots = sorted(path for path, text in texts.items() if dictionary_like(path, text))
    queue = list(roots); visited = set(); targets = {}; issues = []
    while queue:
        path = queue.pop(0)
        if path in visited:
            continue
        visited.add(path)
        text = texts[path]; stream = lex(text)
        for i, (word, start, end) in enumerate(stream):
            if word not in ('#include', '#includeIfPresent'):
                continue
            line = text.count('\n', 0, start) + 1
            if i + 1 == len(stream) or text.count('\n', 0, stream[i+1][1]) + 1 != line:
                issues.append({'path': path, 'line': line, 'reason': 'include_target_missing'})
                continue
            name = stream[i+1][0].strip('"')
            if not name or any(c in name for c in '$#<>'):
                issues.append({'path': path, 'line': line, 'reason': 'include_target_unresolved', 'target': name})
                continue
            try:
                destination = confined(corpus, str(Path(path).parent / name))
                relative = destination.relative_to(corpus.resolve()).as_posix()
            except ValueError:
                issues.append({'path': path, 'line': line, 'reason': 'include_target_outside_corpus', 'target': name})
                continue
            if relative not in inventory or relative not in texts:
                issues.append({'path': path, 'line': line, 'reason': 'include_target_unavailable', 'target': name,
                               'optional': word == '#includeIfPresent'})
                continue
            proof = {'path': path, 'line_start': line, 'line_end': line, 'sha256': inventory[path],
                     'directive': word, 'target': name, 'status': 'literal_include_navigation_not_execution'}
            targets.setdefault(relative, []).append(proof)
            if relative not in visited:
                queue.append(relative)
    return targets, issues


def extract_file(relative, data, force_dictionary=False):
    try:
        text = data.decode('utf-8')
    except UnicodeDecodeError:
        return {'kind':'binary', 'entries':[], 'diagnostics':[], 'text':''}
    if '\x00' in text:
        return {'kind':'binary', 'entries':[], 'diagnostics':[], 'text':''}
    name = Path(relative).name
    is_shell = name.startswith(('Allrun','Allclean')) or text.startswith(('#!/bin/sh','#!/bin/bash'))
    is_dict = force_dictionary or dictionary_like(relative, text)
    entries, diagnostics = parse_dictionary(text) if is_dict else ([], [])
    steps = []
    if is_shell:
        for n, line in enumerate(text.splitlines(),1):
            if re.search(r'\b(runApplication|runParallel)\s+', line) and not line.lstrip().startswith('#'):
                steps.append({'line':n, 'command':line.strip(), 'execution':'static_script_occurrence'})
    return {'kind':'dictionary' if is_dict else 'shell' if is_shell else 'text',
            'entries':entries,'diagnostics':diagnostics,'steps':steps,'text':text}


def scan(corpus):
    inventory = {}
    for folder in ('tutorials', 'manual'):
        for p in sorted((corpus/folder).rglob('*')):
            if p.is_file():
                rel = p.relative_to(corpus).as_posix()
                confined(corpus,rel)
                # All source artifacts are pinned, including visual evidence.
                inventory[rel] = digest(p.read_bytes())
    for name in ('source-checks.json','tutorials-manifest.json'):
        if (corpus/name).exists():
            inventory[name] = digest((corpus/name).read_bytes())
    return inventory


def build(skill=ROOT, corpus=None, index=None, parse_included_dictionaries=False):
    corpus = (corpus or skill/'corpus').resolve()
    index = (index or skill/'index').resolve()
    inventory = scan(corpus)
    # Includes parser, ranking and terminology versions for reproducible invalidation.
    tool_hash = digest(Path(__file__).read_bytes()+Path(__file__).with_name('ranking.py').read_bytes()+Path(__file__).with_name('manual_graph.py').read_bytes()+(skill/'references/terms.json').read_bytes()+encoded({'parse_included_dictionaries':parse_included_dictionaries}))
    snapshot = digest(encoded({'inventory':inventory,'tool':tool_hash,'schema':VERSION}))
    current_file = index/'current.json'
    old = read_json(current_file) if current_file.exists() else None
    if old and old['snapshot'] == snapshot:
        validate(skill, corpus, index)
        return {'status':'unchanged','snapshot':snapshot,'reused_files':sum(p.startswith('tutorials/') for p in inventory)}
    index.mkdir(parents=True,exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.build-',dir=index))
    reused, parsed = 0, 0
    try:
        nodes, edges, docs, issues = {}, [], [], []
        def node(id, kind, **props):
            nodes.setdefault(id, {'id':id, 'kind':kind, **props})
            return id
        def edge(a,b,rel,evidence,status='extracted'):
            edges.append({'source':a,'target':b,'relation':rel,'evidence':evidence,'status':status})
        def evidence(path,start=1,end=None,**extra):
            return {'path':path,'sha256':inventory[path],'line_start':start,
                    'line_end':end or start,**extra}
        def document(id,text,ev,case=None,title='',**extra):
            docs.append({'id':id,'text':text,'title':title,'evidence':ev,'case':case,
                         'terms':dict(Counter(tokens(title+' '+text))),**extra})

        # Canonical alias applies only while both directories exist and match exactly.
        alias = 'tutorials/setRefinedFields/internalDetonation_withObstacleAndGlass'
        canonical = 'tutorials/blastFoam/internalDetonation/internalDetonation_withObstacleAndGlass'
        a = {p[len(alias)+1:]:h for p,h in inventory.items() if p.startswith(alias+'/')}
        b = {p[len(canonical)+1:]:h for p,h in inventory.items() if p.startswith(canonical+'/')}
        aliases = {alias:canonical} if a and a == b else {}
        active_paths = [p for p in inventory if p.startswith('tutorials/') and not any(p.startswith(x+'/') for x in aliases)]
        included, include_issues = (literal_dictionary_includes(corpus, inventory, active_paths)
                                   if parse_included_dictionaries else ({}, []))
        issues.extend(include_issues)
        cases = set()
        for p in active_paths:
            if Path(p).name == 'Allrun':
                cases.add(Path(p).parent.as_posix())
            if p.endswith('/system/controlDict'):
                cases.add(p[:-len('/system/controlDict')])
        for c in sorted(cases):
            node('case:'+c,'case',path=c, label=c.removeprefix('tutorials/'))

        # 与独立手册图共用章节解析及完整证据单元，教程索引仍沿用现有协议。
        concepts = defaultdict(list)
        if any((corpus/'manual/markdown').glob('*.md')):
            module_path = Path(__file__).with_name("manual_graph.py")
            module_spec = importlib.util.spec_from_file_location("principia_skill_manual_graph", module_path)
            manual_graph = importlib.util.module_from_spec(module_spec)
            module_spec.loader.exec_module(manual_graph)
            manual = manual_graph.build(corpus/'manual/markdown')
            manual_nodes = {n['id']: n for n in manual['nodes']}
            for section in (n for n in manual['nodes'] if n['kind'] == 'section'):
                cid = section['id']; title = section['label']; hierarchy = section['hierarchy']
                path = 'manual/markdown/' + section['path']
                ev = evidence(path, section['start'], section['end'], display_path=path)
                node(cid, 'manual_section', title=title, hierarchy=hierarchy, evidence=ev)
                if manual_nodes[section['parent']]['kind'] == 'section':
                    edge(section['parent'], cid, 'HAS_SECTION', ev)
                name = re.sub(r'^\d+(?:\.\d+)*\s+', '', title).strip('` ')
                concepts[name.lower()].append(cid)
                for uid in section['units']:
                    unit = manual_nodes[uid]
                    source_ev = evidence(path, unit['start'], unit['end'], display_path=path)
                    node(uid, 'manual_evidence', evidence=source_ev, block_kinds=unit['block_kinds'])
                    edge(cid, uid, 'DOCUMENTED_ON', source_ev)
                    document(uid, unit['markdown'], source_ev, title=' '.join(hierarchy), source_scope='manual')

        # Version-pinned solver sources are a distinct source category, not manual prose.
        for path in sorted(p for p in inventory if p.startswith('manual/source_code/') and Path(p).suffix in ('.C','.H')):
            text=confined(corpus,path).read_text(encoding="utf-8")
            fid=node('file:'+path,'file',path=path,file_kind='solver_code',sha256=inventory[path])
            lines=text.splitlines()
            for start in range(0,len(lines),48):
                did=f'code:{path}:{start+1}';ev=evidence(path,start+1,min(start+48,len(lines)))
                node(did,'source_span',evidence=ev)
                edge(fid,did,'HAS_SPAN',ev)
                document(did,'\n'.join(lines[start:start+48]),ev,title=path,source_scope='solver_code')

        for path in sorted(active_paths):
            # A root include can change while this fragment's bytes do not.
            # Reachability is an extraction input and must invalidate its cache.
            cache=index/'cache'/tool_hash/(digest(encoded([path,inventory[path],path in included]))+'.json')
            if cache.exists():
                module=read_json(cache)
                reused += 1
            else:
                module=extract_file(path,confined(corpus,path).read_bytes(),force_dictionary=path in included)
                parsed += 1
                temp_cache=cache.with_suffix(f'.{os.getpid()}.tmp')
                write_json(temp_cache,module)
                os.replace(temp_cache,cache)
            text=module['text']
            case=next((c for c in sorted(cases,key=len,reverse=True) if path.startswith(c+'/')),None)
            fid=node('file:'+path,'file',path=path,file_kind=module['kind'],sha256=inventory[path])
            if path in included:
                nodes[fid]['dictionary_inclusion_evidence'] = included[path]
            ev=evidence(path,1,max(1,len(text.splitlines())))
            if case:
                edge('case:'+case,fid,'CONTAINS',ev)
            if not text or (path not in included and Path(path).suffix.lower() in {'.stl','.obj','.csv','.dat'}):
                continue
            # Line-bounded chunks retain dictionary context via per-entry documents below.
            lines=text.splitlines()
            for start in range(0,len(lines),48):
                chunk='\n'.join(lines[start:start+48])
                did=f'text:{path}:{start+1}'
                chunk_ev=evidence(path,start+1,min(start+48,len(lines)))
                node(did,'source_span',evidence=chunk_ev)
                edge(fid,did,'HAS_SPAN',chunk_ev)
                document(did,chunk,chunk_ev,case,title=path,source_scope='tutorial')
            for entry in module['entries']:
                eid=f'config:{path}:{entry["dictionary_path"]}'
                eev=evidence(path,entry['line_start'],entry['line_end'],dictionary_path=entry['dictionary_path'])
                node(eid,'configuration',**entry,evidence=eev,case=case)
                if path in included:
                    nodes[eid].update(extraction_method='dictionary_parser_on_literal_include_target',
                                      evidence_status='tutorial_observed',
                                      scope_note='Physical fragment path; including scope/overrides require following INCLUDES evidence.')
                edge(eid,fid,'DEFINED_IN',eev)
                document(eid,entry['dictionary_path']+' '+entry['value'],eev,case,title=path,source_scope='tutorial')
                value=entry['value'].strip('"')
                matches=concepts.get(value.lower(),[])
                if len(matches)>1:
                    # Only infer scope from explicit dictionary selector names.
                    scopes={'activationModel':'Activation Models','afterburnModel':'Afterburn Models',
                            'equationOfState':'Equation of states','diameterModel':'Diameter models'}
                    scope=scopes.get(entry['key'])
                    matches=[c for c in matches if scope and scope in nodes[c]['hierarchy']]
                if len(matches)==1 and len(value)>2:
                    edge(eid,matches[0],'REFERS_TO_DEFINITION',eev,'name_and_scope_match')
                elif len(matches)>1:
                    issues.append({'path':path,'line':entry['line_start'],'reason':'ambiguous_model_name','value':value})
            for item in module['diagnostics']:
                issues.append({'path':path,**item})
            previous=None
            for step in module.get('steps',[]):
                sid=f'step:{path}:{step["line"]}'
                sev=evidence(path,step['line'],step['line'])
                node(sid,'script_step',**step,evidence=sev,case=case)
                edge(fid,sid,'HAS_STEP',sev)
                command=re.search(r'\b(?:runApplication|runParallel)\s+(\w+)',step['command'])
                if command:
                    definitions=concepts.get(command[1].lower(),[])
                    if len(definitions)==1:
                        edge(sid,definitions[0],'REFERS_TO_DEFINITION',sev,'exact_utility_name_match')
                if previous:
                    edge(previous,sid,'NEXT_IN_SCRIPT',sev)
                previous=sid
            for match in re.finditer(r'^\s*#(include\w*)\s+["<]?([^"\s;>]+)',text,re.M):
                directive,target=match.groups()
                line=text.count('\n',0,match.start())+1
                try:
                    dest=confined(corpus,str(Path(path).parent/target))
                    rel=dest.relative_to(corpus).as_posix()
                except ValueError:
                    rel=''
                if directive in ('include','includeIfPresent') and '$' not in target and rel in inventory:
                    edge(fid,'file:'+rel,'INCLUDES',evidence(path,line,line))
                else:
                    issues.append({'path':path,'line':line,'reason':'unresolved_directive','target':target,'directive':directive})

        # Parent stages are structure, not an invented unconditional execution dependency.
        for c in sorted(cases):
            parents=[p for p in cases if c.startswith(p+'/')]
            if parents:
                parent=max(parents,key=len)
                src=parent+'/Allrun'
                if src in inventory:
                    edge('case:'+parent,'case:'+c,'HAS_STAGE_DIRECTORY',evidence(src))
        # Preserve previously verified errata as evidence documents, not silent rewrites.
        if 'manual/compatibility.md' in inventory:
            path='manual/compatibility.md'
            text=(corpus/path).read_text(encoding="utf-8")
            ev=evidence(path,1,len(text.splitlines()))
            node('errata','source_span',evidence=ev)
            document('errata',text,ev,title='版本 核对 冲突 勘误 compatibility',source_scope='manual')
        # Directly detect README activation mismatches against actual selectors.
        for c in sorted(cases):
            readme=c+'/README.md'
            if readme not in inventory:
                continue
            text=(corpus/readme).read_text(encoding="utf-8")
            stated=re.findall(r'\b(linear|pressureBased|programmedIgnition) activation model\b',text,re.I)
            selectors=[n for n in nodes.values() if n['kind']=='configuration' and n.get('case')==c and n['key']=='activationModel']
            if len(selectors)==1 and stated and selectors[0]['value'].lower()!=stated[0].lower():
                conflict={'case':c,'reason':'readme_configuration_conflict','document_claim':stated[0],
                          'configured_value':selectors[0]['value'],'evidence':[evidence(readme,1,len(text.splitlines())),selectors[0]['evidence']]}
                issues.append(conflict)
                edge('file:'+readme,selectors[0]['id'],'CONFLICTS_WITH',conflict['evidence'][0],'verified_text_comparison')
        # Drop dangling links only for non-indexed resources; record them explicitly.
        valid_edges=[]
        for e in edges:
            if e['source'] in nodes and e['target'] in nodes:
                valid_edges.append(e)
            else:
                issues.append({'reason':'unresolved_graph_reference','edge':e})
        edges=valid_edges
        graph={'schema':VERSION,'snapshot':snapshot,'nodes':list(nodes.values()),'edges':edges,'issues':issues,'aliases':aliases}
        metadata={'schema':VERSION,'snapshot':snapshot,'tool_hash':tool_hash,'inventory':inventory,
                  'counts':{'cases':len(cases),'nodes':len(nodes),'edges':len(edges),'documents':len(docs)},
                  'extraction':'deterministic_structure_and_scoped_name_links',
                  'parse_included_dictionaries':parse_included_dictionaries,
                  'literal_include_targets':len(included),
                  'semantic_llm_extraction':False}
        for name,value in [('graph.json',graph),('documents.json',docs),('manifest.json',metadata)]:
            write_json(stage/name,value)
        check_release(stage,corpus)
        release=index/'releases'/snapshot
        release.parent.mkdir(exist_ok=True)
        if release.exists():
            shutil.rmtree(stage)
        else:
            os.replace(stage,release)
        temp=index/f'.current-{os.getpid()}.json'
        write_json(temp,{'snapshot':snapshot})
        os.replace(temp,current_file)
        return {'status':'built','snapshot':snapshot,'parsed_files':parsed,'reused_files':reused,**metadata['counts']}
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def check_release(release,corpus):
    graph=read_json(release/'graph.json')
    manifest=read_json(release/'manifest.json')
    docs=read_json(release/'documents.json')
    ids={n['id'] for n in graph['nodes']}
    if len(ids)!=len(graph['nodes']):
        raise ValueError('duplicate graph IDs')
    for e in graph['edges']:
        if e['source'] not in ids or e['target'] not in ids:
            raise ValueError('dangling edge')
    for doc in docs:
        if doc['id'] not in ids:
            raise ValueError('document has no node')
        ev=doc['evidence']
        if ev['sha256']!=manifest['inventory'].get(ev['path']):
            raise ValueError('evidence hash mismatch')
        for key in ('path','image_path','display_path'):
            if key in ev and not confined(corpus,ev[key]).is_file():
                raise ValueError('missing evidence '+ev[key])
    if scan(corpus)!=manifest['inventory']:
        raise ValueError('corpus changed: rebuild before querying')
    return {'status':'PASS',**manifest['counts'],'scope':'structure and source identity, not physical validation'}


def release_path(index):
    snapshot=read_json(index/'current.json')['snapshot']
    if not re.fullmatch('[a-f0-9]{64}',snapshot):
        raise ValueError('invalid snapshot pointer')
    return index/'releases'/snapshot


def validate(skill=ROOT,corpus=None,index=None):
    return check_release(release_path(index or skill/'index'),corpus or skill/'corpus')


def query(text,mode='auto',case=None,limit=8,skill=ROOT,corpus=None,index=None,graph_expand=True):
    corpus=corpus or skill/'corpus'; index=index or skill/'index'
    release=release_path(index)
    # Fail closed on deleted/edited evidence, including new cases that affect availability.
    check_release(release,corpus)
    graph=read_json(release/'graph.json'); docs=read_json(release/'documents.json')
    terms=read_json(skill/'references/terms.json')
    q=Counter(tokens(text))
    for term in list(q):
        q[term]=1.0
    lower=text.lower()
    expanded=[]
    for group in terms:
        hits=[x for x in group if (x.lower() in lower if re.search('[\u4e00-\u9fff]',x) else re.search(r'(?<![\w])'+re.escape(x.lower())+r'(?![\w])',lower))]
        if hits:
            expanded.append(group)
            specificity=max((min(1.,len(x)/5) for x in hits if re.search('[\u4e00-\u9fff]',x)),default=0.4)
            for token in set(tokens(' '.join(group))):
                q[token]=max(q.get(token,0),specificity)
    if mode=='auto':
        mode='cases' if re.search('哪个.*(案例|教程)|选.*(案例|教程)|起点|起步|入门',text) else 'search'
    canonical_case=None
    if case:
        canonical_case='tutorials/'+case.removeprefix('tutorials/')
        canonical_case=graph['aliases'].get(canonical_case,canonical_case)
        if not any(n['kind']=='case' and n['path']==canonical_case for n in graph['nodes']):
            return {'status':'case_unavailable','case':case,'snapshot':graph['snapshot'],'results':[]}
    selected=[d for d in docs if (mode!='manual' or d['source_scope']=='manual') and
              (not canonical_case or d['case']==canonical_case or (mode=='search' and d['source_scope']=='manual'))]
    df=Counter(t for d in docs for t in d['terms'])
    avg=sum(sum(d['terms'].values()) for d in docs)/max(1,len(docs))
    scores=[]
    for d in selected:
        length=sum(d['terms'].values()); score=0.; matched=[]
        for term,weight in q.items():
            tf=d['terms'].get(term,0)
            if tf:
                idf=math.log(1+(len(docs)-df[term]+0.5)/(df[term]+0.5))
                score+=weight*idf*tf*2.2/(tf+1.2*(0.25+0.75*length/avg))
                matched.append(term)
        if score:
            title_terms=set(tokens(d['title']))
            score+=sum(weight*1.5 for term,weight in q.items() if term in title_terms)
            if d['source_scope']=='manual' and (d['evidence'].get('pdf_page',10)<10 or d['evidence'].get('pdf_page',10)>=183):
                score*=0.15
            scores.append((score,d,matched))
    scores.sort(key=lambda x:(-x[0],x[1]['id']))
    nodes={n['id']:n for n in graph['nodes']}
    byid={d['id']:d for d in docs}
    outgoing=defaultdict(list); incoming=defaultdict(list)
    for e in graph['edges']:
        outgoing[e['source']].append(e); incoming[e['target']].append(e)
    def result(score,d,matched):
        return {'id':d['id'],'score':round(score,4),'case':d['case'], 'evidence':d['evidence'],
                'excerpt':d['text'][:1200],'matched_terms':matched,'source_scope':d['source_scope']}
    results=[]
    if mode=='cases':
        grouped=defaultdict(list)
        for score,d,matched in scores:
            if d['case']:
                grouped[d['case']].append((score,d,matched))
        ranked=[]
        for c,items in grouped.items():
            # Max evidence score avoids rewarding large cases for containing more files.
            scenes=[x for x in items if x[1]['evidence']['path'].endswith('/README.md')]
            top=scenes[0] if scenes else items[0]
            score=top[0]+0.2*items[0][0] if scenes else 0.6*top[0]
            ordered=[top]+[x for x in items if x[1]['id']!=top[1]['id']]
            ranked.append((score,c,ordered))
        ranked.sort(key=lambda x:(-x[0],x[1]))
        for score,c,items in ranked[:limit]:
            results.append({'case':c.removeprefix('tutorials/'),'score':round(score,4),
                            'match_basis':'textual_evidence_not_verified_task_suitability',
                            'evidence_hits':[result(*item) for item in items[:3]],
                            'issues':[x for x in graph['issues'] if x.get('case')==c]})
    else:
        # Suppress overlapping hits from the same file, retaining distinct dictionary fields.
        seen=[]
        file_counts=Counter()
        for score,d,matched in scores:
            ev=d['evidence']
            if file_counts[ev['path']] >= (2 if canonical_case else 1):
                continue
            if any(ev['path']==p and not (ev['line_end']<a or ev['line_start']>b) for p,a,b in seen):
                continue
            results.append(result(score,d,matched))
            file_counts[ev['path']]+=1
            seen.append((ev['path'],ev['line_start'],ev['line_end']))
            if len(results)>=limit:
                break
    evidence_results=[r for x in results for r in (x.get('evidence_hits') or [x])]
    expanded_edges=[]; related=[]
    if graph_expand:
        import importlib.util
        spec=importlib.util.spec_from_file_location('evidence_ranking',Path(__file__).with_name('ranking.py'))
        ranking=importlib.util.module_from_spec(spec); spec.loader.exec_module(ranking)
        ranked,related,expanded_edges=ranking.select_evidence(
            text,graph,docs,scores,evidence_results,limit if mode!='cases' else 8,result,canonical_case)
        if mode!='cases':
            results=ranked
    relevant_cases={x['case'] for x in evidence_results if x.get('case')}
    if canonical_case:
        relevant_cases.add(canonical_case)
    return {'status':'ok' if results else 'no_lexical_match','snapshot':graph['snapshot'],'mode':mode,
            'query':text,'expanded_term_groups':expanded,'results':results,'related_evidence':related,
            'evidence_contract':'results is the complete bounded evidence list; related_evidence is a subset (except cases mode)',
            'graph_relations':expanded_edges,
            'issues':[x for x in graph['issues'] if x.get('case') in relevant_cases],
            'limits':['Ranking is textual relevance, not physical applicability.',
                      'No matching result does not prove corpus-wide absence.',
                      'Script order preserves source occurrence; conditions are not evaluated.']}


def source(path,start=1,end=None,skill=ROOT,corpus=None,index=None):
    corpus=corpus or skill/'corpus'; index=index or skill/'index'
    manifest=read_json(release_path(index)/'manifest.json')
    if path not in manifest['inventory']:
        raise ValueError('source is not in the published corpus')
    p=confined(corpus,path)
    if digest(p.read_bytes())!=manifest['inventory'][path]:
        raise ValueError('source changed since build')
    lines=p.read_text(encoding="utf-8").splitlines()
    end=min(end or start+79,len(lines))
    if not 1<=start<=end or end-start>=400:
        raise ValueError('invalid range (maximum 400 lines)')
    return {'path':path,'sha256':manifest['inventory'][path],'line_start':start,'line_end':end,
            'text':'\n'.join(f'{i}: {lines[i-1]}' for i in range(start,end+1))}


def main(command=None):
    parser=argparse.ArgumentParser(description=__doc__)
    if command is None:
        parser.add_argument('command',choices=['build','query','source','validate'])
    parser.add_argument('--corpus',type=Path)
    parser.add_argument('--index',type=Path)
    parser.add_argument('--query',default='')
    parser.add_argument('--mode',choices=['auto','cases','manual','search'],default='auto')
    parser.add_argument('--case')
    parser.add_argument('--limit',type=int,default=8)
    parser.add_argument('--path')
    parser.add_argument('--start',type=int,default=1)
    parser.add_argument('--end',type=int)
    parser.add_argument('--no-graph',action='store_true')
    parser.add_argument('--parse-included-dictionaries',action='store_true',
                        help='Parse literal local dictionary include fragments; never execute directives.')
    args=parser.parse_args()
    command=command or args.command
    kwargs={'corpus':args.corpus,'index':args.index}
    if command=='build':
        value=build(**kwargs,parse_included_dictionaries=args.parse_included_dictionaries)
    elif command=='validate':
        value=validate(**kwargs)
    elif command=='source':
        if not args.path:
            parser.error('--path is required')
        value=source(args.path,args.start,args.end,**kwargs)
    else:
        if not args.query.strip() or not 1<=args.limit<=30:
            parser.error('--query is required; --limit must be 1..30')
        value=query(args.query,args.mode,args.case,args.limit,graph_expand=not args.no_graph,**kwargs)
    print(json.dumps(value,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
