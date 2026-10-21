"""Prepare source-only reduced graph variants; preserve evaluated graph identity."""
import argparse
import copy
import json
from pathlib import Path

from chapter2_optimization_200 import read, save, sha, RESOURCES
from chapter2_knowledge_graph_retriever import CONDITION_RELATIONS


def reduced_variants(base):
    """No questions, annotations or performance scores enter this transform."""
    if any('conditions' in n for n in base['nodes'].values()):
        raise ValueError('Expected the evaluated condition-free base')
    if any('conditions' in e or e['relation'] in CONDITION_RELATIONS for e in base['edges']):
        raise ValueError('Condition organization remains')
    variants={};audits={}
    cross=copy.deepcopy(base)
    cross['edges']=[e for e in cross['edges'] if not e['cross_owner']]
    # Legacy graph_variant supports one switch only. Compound variants use an
    # explicit revision profile and the strict manifest-bound adapter below.
    cross.pop('graph_variant',None)
    cross['revision_variant']='selected_no_cross'
    variants['no_cross']=cross
    aliases=copy.deepcopy(base);removed=0;units=0
    for node in aliases['nodes'].values():
        groundings=node.get('alias_grounding')
        if not groundings:continue
        grounded={a for g in groundings for a in g['aliases']}
        original=node.get('aliases',[])
        node['aliases']=[a for a in original if a not in grounded]
        removed+=len(original)-len(node['aliases']);units+=1
        node.pop('alias_grounding')
    aliases['bilingual_alias_revision']={
        'schema':'removed_source_owned_generated_aliases_v1',
        'original_revision':base['bilingual_alias_revision'],
        'aliases_removed':removed,'source_units_affected':units,
        'active_source_units_with_aliases':0,'active_generated_aliases':0}
    aliases.pop('graph_variant',None)
    aliases['revision_variant']='selected_no_source_aliases'
    variants['no_aliases']=aliases
    expected=base['bilingual_alias_revision']
    assert removed==expected['aliases_added'] and units==expected['source_units_with_aliases']
    for name,g in variants.items():
        assert g['units']==base['units'] and g['source_hashes']==base['source_hashes']
        assert set(g['nodes'])==set(base['nodes'])
        for nid,node in base['nodes'].items():
            other=g['nodes'][nid]
            ignored={'aliases','alias_grounding'} if name=='no_aliases' else set()
            assert {k:v for k,v in node.items() if k not in ignored}=={k:v for k,v in other.items() if k not in ignored}
        if name=='no_aliases':assert g['edges']==base['edges']
        assert not any('conditions' in n for n in g['nodes'].values())
        assert not any('conditions' in e or e['relation'] in CONDITION_RELATIONS for e in g['edges'])
        audits[name]=dict(nodes=len(g['nodes']),edges_before=len(base['edges']),edges_after=len(g['edges']),
            edges_removed=len(base['edges'])-len(g['edges']),cross_owner_edges=sum(e['cross_owner'] for e in g['edges']),
            generated_aliases_removed=removed if name=='no_aliases' else 0,
            source_units_exactly_equal=True,source_hashes_exactly_equal=True,node_identities_bodies_anchors_exactly_equal=True,
            original_natural_language_conditions_retained=True)
    return variants,audits


def prepare(source,output):
    if output.exists():raise FileExistsError(output)
    base=read(source);variants,audits=reduced_variants(base)
    output.mkdir(parents=True)
    # Byte identity permits explicit reuse of the existing evaluated baseline;
    # result files continue to identify their original experiment and arm.
    (output/'selected.json').write_bytes(source.read_bytes())
    for name,g in variants.items():save(output/(name+'.json'),g)
    manifest=dict(schema='selected_graph_200_revision_v1',
        selection_source_graph_sha256=sha(source),selection_source=str(source.resolve()),
        builder_sha256=sha(Path(__file__)),source_only_transform=True,
        profiles={name:dict(file=name+'.json',sha256=sha(output/(name+'.json')),
            with_conditions=False,with_cross=name!='no_cross',with_paths=True)
            for name in ['selected','no_cross','no_aliases']},
        selected_graph_counts=dict(nodes=len(base['nodes']),edges=len(base['edges']),
            units=len(base['units']),files=len(base['source_hashes'])),
        audits=audits,model_requests=0,
        new_ablation_results_available=False,
        boundary='Post-result empirical selection. No-op removal of already absent condition edges is not an ablation. New arms require real answers/scoring; old no_cross scores cannot be reused.')
    save(output/'manifest.json',manifest)
    return manifest


def backend(folder,name):
    from chapter2_qa_backends import NativeBackend
    from chapter2_knowledge_graph_v6 import BilingualScopeGraph
    manifest=read(folder/'manifest.json');p=manifest['profiles'][name];path=folder/p['file']
    if sha(path)!=p['sha256']:raise ValueError('Selected graph drift')
    g=read(path)
    if any('conditions' in n for n in g['nodes'].values()) or any('conditions' in e or e['relation'] in CONDITION_RELATIONS for e in g['edges']):
        raise ValueError('Selected graph has structured conditions')
    if name=='no_cross' and any(e['cross_owner'] for e in g['edges']):raise ValueError('Cross-owner ablation not physical')
    if name=='no_aliases' and any(n.get('alias_grounding') for n in g['nodes'].values()):raise ValueError('Generated source aliases remain')
    options={k:p[k] for k in ['with_conditions','with_cross','with_paths']}
    return NativeBackend(BilingualScopeGraph(path,corpus=RESOURCES/'corpus',
        corpus_manifest=RESOURCES/'source-map.json',semantic_policy='unit',options=options),graph=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();print(json.dumps(prepare(a.source,a.output),ensure_ascii=False))
