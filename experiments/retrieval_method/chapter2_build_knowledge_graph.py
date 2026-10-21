"""Cold source-only graph construction with exact deepseek-flash verification."""
import argparse
from concurrent.futures import ThreadPoolExecutor,as_completed
import json
from pathlib import Path
import sys
import time

PROJECT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(PROJECT/'src'))
from principia_core.retrieval.knowledge_qa import FrozenKnowledgeCorpus
from chapter2_graph_sources import prepare_sources,identity
from chapter2_graph_semantics import EXTRACT,VERIFY,curate_extraction,validate_verification,accepted_semantics
from chapter2_offline_dataset_calls import MODEL,ENDPOINT,call,key_from_config,read,save,sha,wire

def body(prompt,payload,max_tokens):
    return {'model':MODEL,'temperature':0,'thinking':{'type':'disabled'},'max_tokens':max_tokens,
      'response_format':{'type':'json_object'},'messages':[{'role':'system','content':prompt},
      {'role':'user','content':wire(payload)}]}

def prepare(corpus,manifest,output,max_chars):
    if output.exists():raise FileExistsError('new graph construction revision required')
    source=FrozenKnowledgeCorpus(corpus,manifest);graph=prepare_sources(source,max_chars=max_chars)
    output.mkdir(parents=True)
    save(output/'source-graph.json',{k:v for k,v in graph.items() if k!='semantic_plans'})
    save(output/'semantic-units.json',graph['semantic_plans'])
    files=[Path(__file__),Path(__file__).parent/'chapter2_graph_sources.py',Path(__file__).parent/'chapter2_graph_semantics.py',
      Path(__file__).parent/'navigation_structure_parser.py',Path(__file__).parent/'chapter2_offline_dataset_calls.py',
      Path(__file__).parent/'chapter2_knowledge_input_guard.py',PROJECT/'src/principia_core/retrieval/knowledge_qa.py']
    fingerprints={p.relative_to(PROJECT).as_posix():sha(p.read_bytes()) for p in files}
    protocol={'schema':'independent_cold_knowledge_graph_build_v1','model':MODEL,'endpoint':ENDPOINT,
      'temperature':0,'thinking':{'type':'disabled'},'source_unit_character_target':max_chars,
      'source_ownership_policy':graph['owner_policy'],'source_manifest_sha256':source.manifest_sha256,
      'source_graph_sha256':sha((output/'source-graph.json').read_bytes()),
      'semantic_units_sha256':sha((output/'semantic-units.json').read_bytes()),
      'semantic_source_unit_ids':sorted(graph['semantic_plans']), 'extract_prompt':EXTRACT,'verify_prompt':VERIFY,
      'source_sha256':fingerprints,'max_transport_attempts':3,'content_retries':0,
      'gold_or_questions_used':False,'identity_policy':'Each node has one original source owner. No global shared entity nodes; cross-source identity is represented by explicit edges.',
      'condition_policy':'Body and aliases exclude applicability clauses; conditions are separately source-verified and never evaluated as satisfied.',
      'raw_source_coverage_files':len(source.hashes),'semantic_generation_scope':'All nonempty markdown sections in the independently selected complete corpus; no QA-based selection.'}
    save(output/'protocol.json',protocol)
    for p in files:
        target=output/'runtime'/p.relative_to(PROJECT)
        target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(p.read_bytes())
    print(wire({'status':'prepared','source_files':len(source.hashes),'units':len(graph['units']),
      'physical_nodes':len(graph['nodes']),'physical_edges':len(graph['edges']),'semantic_units':len(graph['semantic_plans'])}))

def verify_runtime(output):
    protocol=read(output/'protocol.json')
    for relative,value in protocol['source_sha256'].items():
        if sha((PROJECT/relative).read_bytes())!=value:raise ValueError('construction runtime changed; execute its frozen snapshot')
    for filename,key in [('source-graph.json','source_graph_sha256'),('semantic-units.json','semantic_units_sha256')]:
        if sha((output/filename).read_bytes())!=protocol[key]:raise ValueError('frozen construction input drift')
    return protocol

def process(uid,unit,output,key):
    started=time.monotonic();folder=output/'sessions'/identity('session',uid).split(':')[-1]
    numbered=[{'number':unit['start']+i,'text':line} for i,line in enumerate(unit['text'].splitlines())]
    candidate=call('extract',body(EXTRACT,{'source_unit':{**unit,'numbered_lines':numbered}},7000),folder,key,curate_extraction)
    if candidate['status']!='response':return {'unit':uid,'status':candidate['status'],'stage':'extract'}
    verdict=call('verify',body(VERIFY,{'source_unit':unit,'candidate':candidate['parsed']},5000),folder,key,validate_verification)
    if verdict['status']!='response':return {'unit':uid,'status':verdict['status'],'stage':'verify'}
    accepted=accepted_semantics(candidate['parsed'],verdict['parsed'])
    record={'schema':'independently_verified_source_unit_v1','unit_id':uid,'owner':unit['owner'],
      'path':unit['path'],'sha256':unit['sha256'],'start':unit['start'],'end':unit['end'],
      'status':'verified_source_statements_not_execution','accepted':accepted,
      'curation':candidate['parsed']['curation'],
      'extract_response_sha256':sha((folder/'responses/extract.json').read_bytes()),
      'verify_response_sha256':sha((folder/'responses/verify.json').read_bytes()),'seconds':time.monotonic()-started}
    target=folder/'accepted.json'
    if target.exists():
        old=read(target)
        assert old['extract_response_sha256']==record['extract_response_sha256'] and old['verify_response_sha256']==record['verify_response_sha256']
        return {'unit':uid,'status':'verified','definitions':len(old['accepted']['definitions']),'facts':len(old['accepted']['facts'])}
    save(target,record)
    return {'unit':uid,'status':'verified','definitions':len(accepted['definitions']),'facts':len(accepted['facts']),'rejected':len(accepted['rejected'])}

def compile_progress(output,protocol,units):
    records=[];missing=[]
    for uid in sorted(units):
        path=output/'sessions'/identity('session',uid).split(':')[-1]/'accepted.json'
        if path.exists():records.append(read(path))
        else:missing.append(uid)
    responses=[read(p) for p in (output/'sessions').glob('*/responses/*.json')]
    usage=[e['usage'] for r in responses for e in r.get('events',[]) if e.get('usage')]
    summary={'schema':'source_only_semantic_graph_progress_v1','complete':not missing,'units':len(units),'verified_units':len(records),
      'missing_unit_ids':missing,'definitions':sum(len(r['accepted']['definitions']) for r in records),
      'facts':sum(len(r['accepted']['facts']) for r in records),'relations':sum(len(r['accepted']['relations']) for r in records),
      'rejected_items':sum(len(r['accepted']['rejected']) for r in records),'actual_requests':len(responses),
      'transport_attempts':sum(len(r.get('events',[])) for r in responses),
      'known_usage':{k:sum(u.get(k,0) for u in usage) for k in ('prompt_tokens','completion_tokens','total_tokens')},
      'protocol_sha256':sha((output/'protocol.json').read_bytes()),'gold_or_questions_used':False,
      'limits':['Processing every source unit does not prove exhaustive semantic recall.','Rejected and failed facts remain visible; raw source access is unchanged.']}
    save(output/'semantic-progress.json',summary)
    print(wire({k:summary[k] for k in ('complete','units','verified_units','definitions','facts','relations','rejected_items','actual_requests','known_usage')}))
    return summary

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=['prepare','run','progress'])
    p.add_argument('--corpus',type=Path);p.add_argument('--manifest',type=Path);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--max-chars',type=int,default=3000);p.add_argument('--dsh-home',type=Path)
    p.add_argument('--workers',type=int,default=3);p.add_argument('--source-prefix',action='append');p.add_argument('--unit-limit',type=int)
    a=p.parse_args();output=a.output.resolve()
    # Read only the credential before installing the construction input guard.
    key=key_from_config(a.dsh_home) if a.command=='run' else None
    from chapter2_knowledge_input_guard import install
    install()
    if a.command=='prepare':prepare(a.corpus.resolve(),a.manifest.resolve(),output,a.max_chars);return
    protocol=verify_runtime(output);all_units=read(output/'semantic-units.json');units=all_units
    if a.command=='progress':compile_progress(output,protocol,all_units);return
    if a.source_prefix:units={uid:u for uid,u in units.items() if any(u['path'].startswith(prefix) for prefix in a.source_prefix)}
    if a.unit_limit:units=dict(list(units.items())[:a.unit_limit])
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        jobs={pool.submit(process,uid,unit,output,key):uid for uid,unit in units.items()}
        for job in as_completed(jobs):
            try:result=job.result()
            except (ValueError,KeyError,TypeError,AssertionError,RuntimeError,OSError) as exc:
                result={'unit':jobs[job],'status':'processing_error','error_type':type(exc).__name__,'reason':str(exc)[:180]}
                save(output/'sessions'/identity('session',jobs[job]).split(':')[-1]/'processing-error.json',result)
            print(wire(result),flush=True)
    compile_progress(output,protocol,all_units)

if __name__=='__main__':main()
