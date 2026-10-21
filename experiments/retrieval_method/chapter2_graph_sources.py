"""Canonical source ownership for an index-free graph, independent of QA/gold."""
from collections import defaultdict
import hashlib
import json
from pathlib import PurePosixPath
import re
from navigation_structure_parser import dictionary

def identity(kind,*values):
    encoded=json.dumps(values,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')
    return 'knowledge.v1:'+kind+':'+hashlib.sha256(encoded).hexdigest()[:24]

def foam_lex(text):
    # Same conservative token grammar as the existing knowledge.lex. Keep this
    # pure helper here so construction imports no skill runtime or fitted index.
    pattern=r'//[^\n]*|/\*[\s\S]*?\*/|#\{[\s\S]*?#\}|"(?:\\.|[^"\\])*"|[{}();\[\]]|[^\s{}();\[\]]+'
    return [(m.group(),m.start(),m.end()) for m in re.finditer(pattern,text)
            if not m.group().startswith(('//','/*'))]

def markdown_ranges(lines):
    """Partition at every real heading; never bundle sibling sections in a node."""
    boundaries=[];stack=[];fence=None
    for n,line in enumerate(lines,1):
        marker=re.match(r'^\s*(```+|~~~+)',line)
        if marker:
            kind=marker[1][0]
            fence=None if fence==kind else kind if fence is None else fence
            continue
        if fence:continue
        heading=re.match(r'^(#{1,6})\s+(.+?)\s*$',line)
        if heading:
            level=len(heading[1]);stack=[item for item in stack if item['level']<level]
            stack.append({'level':level,'line':n,'title':heading[2]})
            boundaries.append({'start':n,'context':[dict(item) for item in stack],
                               'owner_key':'heading:'+str(n)})
    if not boundaries or boundaries[0]['start']>1:
        boundaries.insert(0,{'start':1,'context':[],'owner_key':'preamble'})
    for i,row in enumerate(boundaries):
        row['end']=boundaries[i+1]['start']-1 if i+1<len(boundaries) else len(lines)
    return [row for row in boundaries if row['end']>=row['start']]

def is_dictionary(path,text):
    return not text.lstrip().startswith('#!') and bool(re.search(r'\bFoamFile\s*\{',text))

def owner_key(record):
    # A phase's reactants/products/initiation and a function object's dictionary
    # are separate source units even when stored in the same physical file.
    components=record['physical_components']
    parents=components if record['kind']=='block' else components[:-1]
    selected=parents[:2]
    return 'dictionary:'+json.dumps(selected,ensure_ascii=False,sort_keys=True,separators=(',',':'))

def dictionary_ranges(lines,parsed):
    owners=['dictionary:[]']*len(lines);depths=[-1]*len(lines)
    # Only block boundaries establish scopes. A leaf/list does not silently
    # invent nested executable dictionaries the conservative parser cannot see.
    for row in parsed['records']:
        if row['kind']!='block':continue
        depth=min(2,len(row['physical_components']))
        for n in range(row['line_start'],row['line_end']+1):
            if depths[n-1]<depth:owners[n-1]=owner_key(row);depths[n-1]=depth
    output=[];start=1
    for n in range(2,len(lines)+2):
        if n>len(lines) or owners[n-1]!=owners[start-1]:
            output.append({'start':start,'end':n-1,'context':[], 'owner_key':owners[start-1]})
            start=n
    return output

def chunks(lines,start,end,max_chars=4500):
    first=start
    while first<=end:
        last=first-1;size=0
        while last<end:
            width=len(lines[last])+len(str(last+1))+3
            if size+width>max_chars and last>=first:break
            size+=width;last+=1
        yield first,last
        first=last+1

def prepare_sources(corpus,max_chars=4500):
    units={};nodes={};edges=[];plans={};issues=[];source_counts={}
    for path in sorted(corpus.hashes):
        lines=corpus.lines(path);raw_text='\n'.join(lines);digest=corpus.hashes[path]
        if not lines:source_counts[path]={'units':0,'empty':True};continue
        parsed=None
        if path.lower().endswith('.md'):
            ranges=markdown_ranges(lines);kind='markdown_section'
        elif is_dictionary(path,raw_text):
            parsed=dictionary(raw_text,foam_lex);ranges=dictionary_ranges(lines,parsed);kind='dictionary_scope'
            issues.extend({'path':path,**item} for item in parsed['issues'])
        else:ranges=[{'start':1,'end':len(lines),'context':[],'owner_key':'text_file'}];kind='original_text'
        by_line={};owner_fragments=defaultdict(list)
        for scope in ranges:
            owner=identity('owner',path,digest,scope['owner_key'])
            for start,end in chunks(lines,scope['start'],scope['end'],max_chars):
                uid=identity('unit',owner,start,end)
                unit={'id':uid,'owner':owner,'path':path,'sha256':digest,'start':start,'end':end,
                    'kind':kind,'context':scope['context'],'owner_key':scope['owner_key'],
                    'text':'\n'.join(lines[start-1:end])}
                units[uid]=unit;owner_fragments[owner].append(uid)
                for n in range(start,end+1):by_line[n]=uid
                label=scope['context'][-1]['title'] if scope['context'] else PurePosixPath(path).name
                nid=identity('raw',uid)
                nodes[nid]={'id':nid,'kind':'original_unit','owner':owner,'unit_id':uid,
                    'path':path,'label':label,'body':unit['text'],'aliases':[],
                    'evidence':[{'path':path,'start':start,'end':end,'sha256':digest}],
                    'state':'literal_source_not_execution'}
                # Semantic generation is source-driven for every markdown
                # section. Dictionaries retain all literal declarations and
                # public typed selectors; no question-based topic selection.
                if kind=='markdown_section' and unit['text'].strip():plans[uid]=unit
        assert set(by_line)==set(range(1,len(lines)+1)),'source partition lost lines'
        for owner,ids in owner_fragments.items():
            for left,right in zip(ids,ids[1:]):
                edges.append({'id':identity('edge',left,right,'SAME_SOURCE_SCOPE'),
                    'source':identity('raw',left),'target':identity('raw',right),'relation':'SAME_SOURCE_SCOPE',
                    'conditions':[],'status':'same_physical_scope'})
        if parsed:
            record_ids={}
            for row in parsed['records']:
                # Whole block bodies can contain other owners. Only the header
                # anchors a block node; each leaf's actual text remains separate.
                start=row['line_start'];uid=by_line[start];unit=units[uid]
                end=start if row['kind']=='block' else min(row['line_end'],unit['end'])
                clipped=row['kind']!='block' and end<row['line_end']
                flags=row['flags']+(['literal_spans_source_fragment_not_indexed_as_value'] if clipped else [])
                nid=identity('literal',path,digest,row['ordinal']);record_ids[row['ordinal']]=nid
                conditions=[{'text':f"{c['directive']} branch={c['branch']}", 'source_line':c['line'],
                    'evaluated':False} for c in row['conditional_context']]
                nodes[nid]={'id':nid,'kind':'dictionary' if row['kind']=='block' else 'configuration',
                    'owner':unit['owner'],'unit_id':uid,'path':path,'label':row['dictionary_path'],
                    'key':row['key'],'value':'' if clipped else row.get('value_text',row.get('argument_text','')),
                    'components':row['components'],'physical_components':row['physical_components'],
                    'dictionary':row['dictionary_path'],
                    'body':'\n'.join(lines[start-1:end]),'aliases':[], 'conditions':conditions,
                    'flags':flags,'literal_kind':row['kind'],
                    'evidence':[{'path':path,'start':start,'end':end,'sha256':digest}],
                    'state':'unresolved_static_source' if flags else row['status']}
                edges.append({'id':identity('edge',identity('raw',uid),nid,'HAS_LITERAL'),
                    'source':identity('raw',uid),'target':nid,'relation':'HAS_LITERAL',
                    'conditions':[],'status':'physical_source'})
            for row in parsed['records']:
                if row['parent'] is not None:
                    parent=record_ids[row['parent']];child=record_ids[row['ordinal']]
                    edges.append({'id':identity('edge',parent,child,'HAS_ENTRY'),
                        'source':parent,'target':child,'relation':'HAS_ENTRY','conditions':[],
                        'status':'physical_nesting_not_effective_values'})
        source_counts[path]={'units':len(set(by_line.values())),'empty':False,'literal_records':len(parsed['records']) if parsed else 0}
    result={'schema':'independent_knowledge_graph_sources_v1','corpus_manifest_sha256':corpus.manifest_sha256,
        'units':units,'nodes':nodes,'edges':edges,'semantic_plans':plans,'source_counts':source_counts,
        'parser_issues':issues,'gold_or_questions_used':False,
        'owner_policy':'markdown heading section; dictionary outer two physical ancestors; other text file. Long slices retain the same logical owner. No global unowned entity nodes.',
        'limits':['Physical structure does not establish include expansion, overrides or execution.','Opaque dictionary lists are not silently expanded into unsupported nested scopes.']}
    return result
