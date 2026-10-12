"""Global source-grounded retrieval graph: units, provenance, incremental assembly and lookup."""
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
RELATIONS = {'DESCRIBES','USES_MODEL','CONFIGURED_IN','REQUIRES_INPUT','PRODUCES','EXECUTES','SUPPORTS','LIMITS','DEFINES_PARAMETER','FORMULA_REFERENCE','RECOMMENDS','CONFLICTS'}
KINDS = {'model','solver','utility','parameter','field','file','case','concept'}
RESOURCE_SUFFIXES = {'.stl','.obj','.eps','.msh','.inp','.fbd','.nam','.csv','.xy','.12d','.foam'}


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def digest(value):
    return hashlib.sha256(value if isinstance(value, bytes) else value.encode()).hexdigest()


def read(path):
    return json.loads(path.read_text())


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(encoded(value) + '\n')
    temporary.replace(path)


def inventory(skill=ROOT):
    return {str(p.relative_to(skill/'corpus')): digest(p.read_bytes())
            for p in sorted((skill/'corpus').rglob('*')) if p.is_file()}


def source_blocks(path, text, sha, page=None, maximum=7000):
    lines = text.splitlines(keepends=True)
    start = 0
    while start < len(lines):
        end, size = start, 0
        while end < len(lines) and (size + len(lines[end]) <= maximum or end == start):
            size += len(lines[end]); end += 1
        yield {'id': f'{path}@{start+1}', 'path': path, 'line_start': start+1,
               'text': ''.join(lines[start:end]), 'sha256': sha, 'pdf_page': page, 'target': True}
        start = end


def make_plan(skill=ROOT, model='deepseek-flash'):
    if model != 'deepseek-flash':
        raise ValueError('global extraction requires deepseek-flash')
    hashes = inventory(skill)
    current = read(skill/'index/current.json')['snapshot']
    structure = read(skill/'index/releases'/current/'graph.json')
    cases = sorted((n['path'] for n in structure['nodes'] if n['kind']=='case'), key=lambda x: (-len(x), x))
    aliases = structure.get('aliases', {})
    units, resources = [], []
    for source in sorted((skill/'corpus/manual/markdown').glob('*.md')):
        path = source.relative_to(skill/'corpus').as_posix()
        for block in source_blocks(path, source.read_text(), hashes[path]):
            units.append({'id': 'manual:'+block['id'], 'scope':'manual',
                          'case':None, 'sources':[block]})
    grouped = defaultdict(list)
    for path, sha in hashes.items():
        if not path.startswith('tutorials/'): continue
        alias = next((a for a in aliases if path == a or path.startswith(a+'/')), None)
        if alias:
            resources.append({'path':path,'sha256':sha,'reason':'verified_alias_in_structural_index','canonical':aliases[alias]})
            continue
        if Path(path).suffix.lower() in RESOURCE_SUFFIXES:
            resources.append({'path':path,'sha256':sha,'reason':'geometry_mesh_plot_or_numeric_resource; structure and original retained'})
            continue
        try: text = (skill/'corpus'/path).read_text()
        except UnicodeError:
            resources.append({'path':path,'sha256':sha,'reason':'non_utf8_resource; structure retained'}); continue
        if not text.strip():
            resources.append({'path':path,'sha256':sha,'reason':'empty_resource'}); continue
        case = next((c for c in cases if path.startswith(c+'/')), str(Path(path).parent))
        grouped[case].extend(source_blocks(path,text,sha))
    for case, blocks in sorted(grouped.items()):
        batch, count, size = [], 0, 0
        for block in blocks:
            if batch and size+len(block['text']) > 14000:
                units.append({'id':f'{case}:part{count}', 'scope':'tutorial','case':case,'sources':batch})
                batch, size, count = [], 0, count+1
            batch.append(block);size += len(block['text'])
        if batch: units.append({'id':f'{case}:part{count}','scope':'tutorial','case':case,'sources':batch})
    prompt = (skill/'references/global-extraction-prompt.md').read_text()
    extraction = {'model':model,'thinking':'disabled','temperature':0,'max_tokens':6000,
                  'prompt_sha256':digest(prompt),'unit_schema':'source-block-v1'}
    for unit in units:
        unit['cache_key'] = digest(encoded({'unit':unit,'extraction':extraction}))
    return {'corpus_hashes':hashes,'structure_snapshot':current,'extraction':extraction,
            'units':units,'resources':resources,'case_paths':sorted(cases)}


def compact(text):
    return re.sub(r'\s+', '', text)


def locate_quote(source, quote):
    if not isinstance(quote,str) or len(compact(quote)) < 4:
        raise ValueError('quote too short')
    text=source['text']; needle=compact(quote)
    # Ignore whitespace only, retaining punctuation/case/symbol identity.
    positions=[i for i,c in enumerate(text) if not c.isspace()]
    hay=''.join(text[i] for i in positions); start=hay.find(needle)
    if start<0: raise ValueError('quote not in supplied source')
    if hay.find(needle,start+1)>=0: raise ValueError('ambiguous quote; longer source anchor required')
    a,b=positions[start],positions[start+len(needle)-1]+1
    return {'path':source['path'],'sha256':source['sha256'],
            'line_start':source['line_start']+text[:a].count('\n'),
            'line_end':source['line_start']+text[:b-1].count('\n'),
            'quote':text[a:b],'pdf_page':source['pdf_page']}


def entity_id(entity):
    return encoded([entity['kind'],entity.get('namespace',''),entity['name']])


def validate_cards(unit, payload):
    if not isinstance(payload,dict) or not isinstance(payload.get('cards'),list):
        raise ValueError('cards must be a list')
    sources={s['id']:s for s in unit['sources']}; accepted=[]; rejected=[]
    for ordinal, card in enumerate(payload['cards']):
        try:
            if not isinstance(card,dict) or card.get('relation') not in RELATIONS: raise ValueError('invalid relation')
            for key in ['title','subject','object','conditions_zh']:
                if not isinstance(card.get(key),str): raise ValueError('missing textual card field')
            entities=card.get('entities')
            if not isinstance(entities,list) or not entities: raise ValueError('missing entities')
            for entity in entities:
                if (not isinstance(entity,dict) or entity.get('kind') not in KINDS or
                    not isinstance(entity.get('name'),str) or not entity['name'].strip() or
                    not isinstance(entity.get('namespace',''),str)):
                    raise ValueError('invalid entity')
            anchors=card.get('anchors')
            if not isinstance(anchors,list) or not anchors: raise ValueError('missing anchors')
            evidence=[]; target=False
            for anchor in anchors:
                source=sources[anchor['source']]
                evidence.append(locate_quote(source,anchor['quote']))
                target |= source['target']
            if not target: raise ValueError('no evidence on target source')
            if type(card.get('visual_check_required')) is not bool: raise ValueError('missing visual status')
            fact={k:card[k] for k in ('title','subject','relation','object','entities','conditions_zh','visual_check_required')}
            # Case membership comes from the source inventory, not an inferred physical relation.
            if unit['case']:
                fact['entities']=[*entities,{'kind':'case','namespace':'source_inventory','name':unit['case']}]
            fact.update({'scope':unit['scope'],'case':unit['case'],'evidence':evidence,
                         'review':'model_extracted_source_locator_checked_not_semantically_reviewed','executable':False})
            fact['id']='card:'+digest(encoded(fact))[:24]
            accepted.append(fact)
        except (ValueError,KeyError,TypeError) as exc:
            rejected.append({'ordinal':ordinal,'reason':str(exc)})
    return accepted,rejected


def assemble(plan, skill=ROOT):
    cards={}; coverage=[]; faults=[]
    for unit in plan['units']:
        path=skill/'semantic/global/cache'/f"{unit['cache_key']}.json"
        if not path.exists(): raise ValueError('unprocessed unit: '+unit['id'])
        response=read(path)
        if response.get('status')!='ok': raise ValueError('failed unit: '+unit['id'])
        if response.get('cache_key')!=unit['cache_key'] or response.get('model')!=plan['extraction']['model']:
            raise ValueError('extraction model/cache mismatch: '+unit['id'])
        try: accepted,rejected=validate_cards(unit,response['payload'])
        except ValueError as exc: accepted,rejected=[],[{'reason':str(exc)}]
        cards.update({c['id']:c for c in accepted})
        coverage.append({'unit':unit['id'],'scope':unit['scope'],'case':unit['case'],
                         'cache_key':unit['cache_key'],'target_sources':sorted({s['path'] for s in unit['sources'] if s['target']}),
                         'status':'extracted_with_rejected_candidates' if rejected else 'extracted_candidates' if accepted else 'processed_no_accepted_cards',
                         'accepted':len(accepted),'rejected':len(rejected),
                         'summary_zh':response['payload'].get('summary_zh',''),
                         'deferred':response['payload'].get('deferred',[]),
                         'visual_review_complete':False,'semantic_review_complete':False})
        faults.extend({'unit':unit['id'],**r} for r in rejected)
    entities={}; links=[]
    for card in cards.values():
        for entity in card['entities']:
            eid=entity_id(entity)
            entities[eid]={'id':eid,**entity}
            links.append({'source':eid,'relation':card['relation'],'target':card['id']})
    snapshot=digest(encoded({'sources':plan['corpus_hashes'],'extraction':plan['extraction'],
                            'unit_keys':[u['cache_key'] for u in plan['units']],'cards':sorted(cards)}))
    graph={'snapshot':snapshot,'entities':list(entities.values()),'cards':list(cards.values()),'edges':links,
           'limits':['candidate locator graph, not verified physical dependency graph','exact entity kind/namespace/name identities; no fuzzy merges']}
    manifest={'snapshot':snapshot,'corpus_hashes':plan['corpus_hashes'],'structure_snapshot':plan['structure_snapshot'],
              'extraction':plan['extraction'],'coverage':coverage,'resources':plan['resources'],
              'case_paths':plan['case_paths'],'rejected_candidates':faults,
              'counts':{'units':len(coverage),'manual_units':sum(u['scope']=='manual' for u in coverage),
                        'tutorial_units':sum(u['scope']=='tutorial' for u in coverage),'cards':len(cards),'entities':len(entities),
                        'edges':len(links),'rejected_candidates':len(faults),'resource_files':len(plan['resources'])}}
    if inventory(skill)!=plan['corpus_hashes']: raise ValueError('corpus changed during build')
    release=skill/'semantic/global/releases'/snapshot
    write(release/'graph.json',graph);write(release/'manifest.json',manifest)
    write(skill/'semantic/global/current.json',{'snapshot':snapshot})
    return manifest


class GlobalGraph:
    def __init__(self, skill=ROOT, validate_sources=True):
        self.skill=skill
        snapshot=read(skill/'semantic/global/current.json')['snapshot']
        release=skill/'semantic/global/releases'/snapshot
        self.manifest=read(release/'manifest.json');self.graph=read(release/'graph.json')
        if validate_sources and inventory(skill)!=self.manifest['corpus_hashes']:
            raise ValueError('source changes require rebuilding global graph')
        self.cards={c['id']:c for c in self.graph['cards']}
        self.entities={e['id']:e for e in self.graph['entities']}
        self.adj=defaultdict(list)
        for edge in self.graph['edges']:self.adj[edge['source']].append(edge)

    def lookup(self, terms, relations=None, case=None, limit=60, scope=None):
        # Entity labels only: no document BM25, no corpus-specific score weights.
        terms=[t.strip().casefold() for t in terms if isinstance(t,str) and len(t.strip())>1]
        matched=[]
        for eid,entity in self.entities.items():
            label=entity['name'].casefold()
            hits=sum(t==label or bool(re.search(r'(?<![a-z0-9_])'+re.escape(t)+r'(?![a-z0-9_])',label)) for t in terms)
            if hits:matched.append((sum(t==label for t in terms),hits,eid))
        matched.sort(key=lambda v:(-v[0],-v[1],v[2]))
        candidates={}
        for exact,hits,eid in matched:
            for edge in self.adj[eid]:
                if relations and edge['relation'] not in relations:continue
                card=self.cards[edge['target']]
                if scope and card['scope']!=scope:continue
                if case and card['case'] and card['case']!=case:continue
                candidate={'card':card,'entity':self.entities[eid],'path':[edge],'entity_match':{'exact':exact,'matched_terms':hits}}
                old=candidates.get(card['id'])
                if old is None or (exact,hits)>(old['entity_match']['exact'],old['entity_match']['matched_terms']):
                    candidates[card['id']]=candidate
        results=sorted(candidates.values(),key=lambda r:(-r['entity_match']['exact'],-r['entity_match']['matched_terms'],r['card']['evidence'][0]['path'],r['card']['evidence'][0]['line_start'],r['card']['id']))
        return {'status':'ok' if results else 'no_entity_evidence','snapshot':self.graph['snapshot'],
                'matched_entity_count':len(matched),'total_cards':len(results),'results':results[:limit],
                'truncated':len(results)>limit,'limits':self.graph['limits']}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--terms',nargs='+',required=True);parser.add_argument('--relation',action='append');parser.add_argument('--case');parser.add_argument('--limit',type=int,default=20)
    args=parser.parse_args()
    print(json.dumps(GlobalGraph().lookup(args.terms,args.relation,args.case,args.limit),ensure_ascii=False,indent=2))


if __name__=='__main__':main()
