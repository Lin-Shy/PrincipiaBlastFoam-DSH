"""Deterministic graph ablation artifacts with a content-preservation audit."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
from chapter2_knowledge_graph_retriever import CONDITION_RELATIONS
from chapter2_offline_dataset_calls import read,save,sha

def variant(graph,name):
    if name not in {'full','no_cross','no_conditions','no_extension'}:raise ValueError('unknown graph variant')
    result=copy.deepcopy(graph);before=len(result['edges'])
    if name=='no_cross':result['edges']=[e for e in result['edges'] if not e['cross_owner']]
    elif name=='no_conditions':
        for n in result['nodes'].values():n.pop('conditions',None)
        result['edges']=[{k:v for k,v in e.items() if k!='conditions'} for e in result['edges'] if e['relation'] not in CONDITION_RELATIONS]
    elif name=='no_extension':result['edges']=[]
    strip=lambda n:{k:v for k,v in n.items() if k!='conditions'}
    assert result['units']==graph['units'] and result['source_hashes']==graph['source_hashes']
    assert set(result['nodes'])==set(graph['nodes'])
    assert all(strip(result['nodes'][nid])==strip(n) for nid,n in graph['nodes'].items())
    result['graph_variant']=name
    audit={'variant':name,'nodes_before':len(graph['nodes']),'nodes_after':len(result['nodes']),
      'edges_before':before,'edges_after':len(result['edges']),
      'source_units_exactly_equal':True,'source_hashes_exactly_equal':True,'node_bodies_aliases_anchors_exactly_equal':True,
      'cross_owner_edges_after':sum(e['cross_owner'] for e in result['edges']),
      'condition_fields_after':sum('conditions' in n for n in result['nodes'].values())+sum('conditions' in e for e in result['edges']),
      'condition_edges_after':sum(e['relation'] in CONDITION_RELATIONS for e in result['edges']),
      'limits':['Original source clauses remain in raw text in every variant.',
        'Typed physical identity disambiguation is retained; no-condition estimates explicit applicability organization.']}
    return result,audit

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--graph',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--allow-partial-development',action='store_true')
    a=p.parse_args();graph=read(a.graph)
    if not graph['semantic_processing_complete'] and not a.allow_partial_development:raise ValueError('partial development graph')
    if a.output.exists():raise FileExistsError('ablation artifact revision is immutable')
    audits=[]
    for name in ('full','no_cross','no_conditions','no_extension'):
        g,audit=variant(graph,name);target=a.output/(name+'.json');save(target,g)
        audits.append({**audit,'artifact_sha256':sha(target.read_bytes())})
    save(a.output/'ablation-audit.json',{'schema':'source_owned_graph_ablation_difference_v1',
      'base_graph_sha256':sha(a.graph.read_bytes()),'implementation_sha256':sha(Path(__file__).read_bytes()),'variants':audits})
    print(json.dumps(audits))

if __name__=='__main__':main()
