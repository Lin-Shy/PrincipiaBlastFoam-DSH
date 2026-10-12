"""Connect complete manual structure and explicitly accepted source-backed facts."""
import argparse
from collections import defaultdict
from pathlib import Path
import re

import evidence_bundle as b
import manual_graph as m


def title(label):
    return re.sub(r'^\d+(?:\.\d+)*\s*', '', label).strip(' `')


def named(name, query):
    return len(name) >= 3 and re.search(r'(?<![A-Za-z0-9_])' + re.escape(name) + r'(?![A-Za-z0-9_])', query, re.I) is not None


def build(engine, foundation=None, semantic=None, review=None):
    foundation = foundation or m.build(engine.skill/'corpus/manual/markdown')
    m.validate(foundation, engine.skill/'corpus/manual/markdown')
    nodes = {n['id']: n for n in foundation['nodes']}
    lookup = {(u['path'], u['start'], u['end']): uid for uid,u in engine.units.items()}
    mapping = {}; metadata = {}; edges = []
    for n in nodes.values():
        if n['kind'] != 'evidence': continue
        key = ('manual/markdown/'+n['path'], n['start'], n['end'])
        uid = lookup.get(key)
        if uid is None: raise ValueError('manual evidence not aligned with bundle')
        mapping[n['id']] = uid
        section = nodes[n['section']]
        ancestors=[]; parent=nodes[section['parent']]
        while parent['kind']=='section':
            ancestors.append(parent['id']); parent=nodes[parent['parent']]
        metadata[uid] = {'section': section['id'], 'ancestors': ancestors, 'name': title(section['label']),
                         'title': ' > '.join(section['hierarchy'])}
    def units(nid):
        n = nodes[nid]
        return [mapping[nid]] if nid in mapping else [mapping[u] for u in n.get('units', [])]
    def link(a,z,relation,evidence,status):
        if a != z:
            edges.append({'source':a,'target':z,'relation':relation,'evidence':evidence,'status':status})
    for n in nodes.values():
        if n['kind'] != 'section': continue
        us=units(n['id'])
        for a,z in zip(us, us[1:]): link(a,z,'SECTION_CONTEXT',[],'same_section_not_dependency')
        parent=nodes[n['parent']]
        if parent['kind']=='section':
            for a in us:
                for z in units(parent['id']):link(a,z,'PARENT_CONTEXT',[],'ancestor_context_not_dependency')
    for edge in foundation['edges']:
        if edge['relation'] not in ('REFERS_TO_SECTION','REFERS_TO_FORMULA'):continue
        target=nodes[edge['target']];targets=units(target['id'])
        source=nodes[edge['source']]
        # Resolve a named subsection only inside an explicitly cited chapter.
        if target['kind']=='section':
            matches=[n for n in nodes.values() if n['kind']=='section' and n['path']==target['path']
                and target['start']<n['start']<=target['subtree_end'] and named(title(n['label']),source['markdown'])]
            if matches:targets=[u for n in matches for u in units(n['id'])]
        for a in units(edge['source']):
            for z in targets:link(a,z,edge['relation'],[{'path':'manual/markdown/'+source['path'],
                'line_start':edge['line_start'],'quote':edge['quote']}],'explicit_reference')
    facts=[];entities={}
    if semantic is not None:
        if review is None:raise ValueError('explicit semantic review required')
        if semantic['foundation_snapshot']!=foundation['snapshot']:raise ValueError('semantic foundation mismatch')
        if review['semantic_snapshot']!=semantic['snapshot']:raise ValueError('semantic review mismatch')
        if b.sha({k:v for k,v in semantic.items() if k!='snapshot'})!=semantic['snapshot']:
            # Existing semantic files use the manual graph canonical encoding.
            if m.sha(m.encoded({k:v for k,v in semantic.items() if k!='snapshot'}))!=semantic['snapshot']:
                raise ValueError('semantic digest mismatch')
        decisions={d['fact']:d for d in review['decisions']}
        for fact in semantic['facts']:
            decision=decisions.get(fact['id'],{})
            if decision.get('status')!='accept':continue
            proof=[];anchors=[]
            for ev in fact['evidence']:
                n=nodes[ev['source']]
                path='manual/markdown/'+ev['path']
                if path not in engine.graph['inventory'] or engine.graph['inventory'][path]!=ev['sha256']:
                    raise ValueError('fact source hash mismatch')
                text=''.join(engine.texts[path][ev['line_start']-1:ev['line_end']])
                if not ev['quote'] or ev['quote'] not in text:raise ValueError('fact quote mismatch')
                if n['path']!=ev['path'] or not n['start']<=ev['line_start']<=ev['line_end']<=n['end']:
                    raise ValueError('fact source range mismatch')
                proof.append({'path':path,'start':ev['line_start'],'end':ev['line_end'],'quote':ev['quote']})
                anchors+=units(ev['source'])
            for entity in (fact['subject'],fact['object']):
                if entity['scope'] not in nodes:raise ValueError('unknown entity scope')
                entities[entity['id']]=entity
            for uid in decision.get('additional_source_units',[]):
                n=nodes[uid]
                if n['section']!=fact['section']:raise ValueError('review source outside fact section')
                anchors+=units(uid)
                proof.append({'path':'manual/markdown/'+n['path'],'start':n['start'],'end':n['end'],'quote':n['markdown']})
            f={k:fact[k] for k in ('id','subject','object','relation','summary_zh','conditions_zh')}
            f.update(evidence=proof,anchors=sorted(set(anchors)),review='accepted_by_source_review',
                     section=fact['section'])
            facts.append(f)
            for entity in (fact['subject'],fact['object']):
                for a in f['anchors']:
                    for z in units(entity['scope']):link(a,z,'ENTITY_DEFINITION',proof,'accepted_fact_scope')
    result={'version':'domain-graph-v1','builder_sha256':b.sha(Path(__file__).read_bytes()),
        'base_snapshot':engine.graph['snapshot'],'foundation_snapshot':foundation['snapshot'],
        'semantic_snapshot':semantic['snapshot'] if semantic else None,'review_sha256':b.sha(review) if review else None,
        'metadata':metadata,'entities':entities,'facts':facts,'edges':list({b.wire(e):e for e in edges}.values()),
        'coverage':{'structural_documents':len({u['path'] for u in engine.units.values() if u['path'].startswith('manual/markdown/')}),
                    'accepted_facts':len(facts),'semantic_documents':sorted({ev['path'] for f in facts for ev in f['evidence']})}}
    result['snapshot']=b.sha(result)
    return result


def validate(data, engine):
    if data['base_snapshot']!=engine.graph['snapshot']:raise ValueError('domain base mismatch')
    if data['builder_sha256']!=b.sha(Path(__file__).read_bytes()):raise ValueError('domain builder changed; rebuild')
    if b.sha({k:v for k,v in data.items() if k!='snapshot'})!=data['snapshot']:raise ValueError('domain digest mismatch')
    return data


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--foundation',type=Path);p.add_argument('--semantic',type=Path);p.add_argument('--review',type=Path)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();engine=b.EvidenceSearch()
    data=build(engine,*(b.k.read_json(path) if path else None for path in (args.foundation,args.semantic,args.review)))
    b.k.write_json(args.output,data)
    print(b.wire({'snapshot':data['snapshot'],'edges':len(data['edges']),**data['coverage']}))


if __name__=='__main__':main()
