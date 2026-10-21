"""Source-only runtime, original-delivery and ablation audit; zero model calls."""
import argparse
import json
from pathlib import Path
import sys
import time
PROJECT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(PROJECT/'src'))
from principia_core.retrieval.knowledge_qa import FrozenKnowledgeCorpus,KnowledgeToolSession,KnowledgeBudget
from chapter2_qa_backends import create_backend
from chapter2_offline_dataset_calls import save,sha

PROBES=['freeFieldC4 RDX reactants equationOfState Murnaghan',
 'overpressure pRef fieldMinMax store', 'table equationOfState thermo rho p e T',
 'twoCharge phaseProperties activationModel linear', 'blastFSIFoam preCICE fluid solid',
 'beginUnrefine fieldValue delta']

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--corpus',type=Path,required=True)
    p.add_argument('--manifest',type=Path,required=True);p.add_argument('--source-map',type=Path,required=True)
    p.add_argument('--variants',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--allow-partial-development',action='store_true');a=p.parse_args()
    from chapter2_knowledge_input_guard import install
    install()
    corpus=FrozenKnowledgeCorpus(a.corpus,a.manifest);events=[];boundaries={}
    for name in ('full','no_cross','no_conditions','no_extension'):
        path=a.variants/(name+'.json');options={'with_cross':name!='no_cross','with_conditions':name!='no_conditions',
          'with_paths':name!='no_extension','allow_partial_development':a.allow_partial_development}
        backend=create_backend('graph',a.corpus,a.source_map,graph=path,graph_options=options)
        boundaries[name]=backend.engine.owner_boundary_audit()
        if name=='no_cross':assert boundaries[name]['maximum_owners_per_component']==1 and boundaries[name]['cross_owner_edges_retained']==0
        for query in PROBES:
            tools=KnowledgeToolSession('graph',corpus,backend,KnowledgeBudget())
            result=json.loads(tools.execute('search',{'query':query}));event=tools.events[-1]
            assert event['status']=='returned' and event['delivered_characters']<=6000
            for e in result['evidence']:
                assert e['lines']==corpus.read(e['path'],e['start'],e['end'])['lines']
            ranking=backend.events[-1]['native_packet']['native_ranking']
            if name=='no_cross':assert all(not e['cross_owner'] for r in ranking['items'] for e in r['route'])
            if name=='no_conditions':assert all(not r['conditions'] and all(not e['conditions'] for e in r['route']) for r in ranking['items'])
            if name=='no_extension':assert ranking['diagnostic']['expanded_edges']==0
            events.append({'variant':name,'query':query,'characters':event['delivered_characters'],
              'delivered_original_lines':event['delivered_original_lines'],'native_event':backend.events[-1]})
    forbidden=[n for n in sys.modules if n.split('.')[0] in {'torch','numpy','sentence_transformers','rank_bm25','faiss','sklearn'} or n=='chapter2_baseline_native']
    assert not forbidden,'graph loaded an external ranking/index dependency'
    if a.output.exists():raise FileExistsError('audit revision is immutable')
    source_files=[Path(__file__),PROJECT/'experiments/retrieval_method/chapter2_qa_backends.py',
      PROJECT/'experiments/retrieval_method/chapter2_knowledge_graph_retriever.py',
      PROJECT/'experiments/retrieval_method/chapter2_knowledge_input_guard.py',
      PROJECT/'experiments/retrieval_method/chapter2_offline_dataset_calls.py',
      PROJECT/'src/principia_core/retrieval/knowledge_qa.py']
    fingerprints={f.relative_to(PROJECT).as_posix():sha(f.read_bytes()) for f in source_files}
    for f in source_files:
        target=a.output.with_suffix('')/'runtime'/f.relative_to(PROJECT)
        target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(f.read_bytes())
    save(a.output,{'schema':'source_owned_graph_runtime_audit_v1','model_calls':0,
      'runtime_source_sha256':fingerprints,
      'production_corpus_manifest_sha256':corpus.manifest_sha256,
      'variant_bindings':{n:sha((a.variants/(n+'.json')).read_bytes()) for n in boundaries},
      'owner_boundary_components':boundaries,'external_index_modules_loaded':forbidden,
      'implementation_sha256':sha(Path(__file__).read_bytes()),'events':events,
      'development_partial_graph':a.allow_partial_development,
      'limits':['These probes test permissions, delivery and mechanisms; they are not a QA accuracy result.']})
    print(json.dumps({'events':len(events),'model_calls':0,'external_index_modules_loaded':forbidden,'no_cross':boundaries['no_cross']}))

if __name__=='__main__':main()
