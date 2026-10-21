"""Frozen, resumable online Qwen QA; consumes natural questions and raw artifacts."""
import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys
import ssl
import time
from urllib.request import Request,build_opener,ProxyHandler,HTTPSHandler
from urllib.error import HTTPError,URLError

PROJECT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(PROJECT/'src'))
from principia_core.retrieval.knowledge_agent import AutonomousKnowledgeAgent,ModelBudget,SYSTEM
from principia_core.retrieval.knowledge_qa import FrozenKnowledgeCorpus,KnowledgeToolSession,KnowledgeBudget,wire
from chapter2_qwen_proxy_config import settings

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def save(p,v):
    p.parent.mkdir(parents=True,exist_ok=True);temp=p.with_suffix('.tmp')
    temp.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');temp.replace(p)

def urlopen(request,timeout,context):
    # The authorized API endpoint is unchanged. Do not inherit the unreliable
    # machine-local Windows HTTP proxy into this independently frozen client.
    opener=build_opener(ProxyHandler({}),HTTPSHandler(context=context))
    return opener.open(request,timeout=timeout)

class RecordedQwenClient:
    def __init__(self,endpoint,key,folder):
        self.endpoint,self.key,self.folder=endpoint,key,folder
        self.context=ssl.create_default_context()
        self.context.minimum_version=ssl.TLSVersion.TLSv1_2
        self.context.maximum_version=ssl.TLSVersion.TLSv1_2
    def __call__(self,body,turn):
        path=self.folder/f'{turn:02d}.json';data=wire(body).encode('utf-8')
        fingerprint=hashlib.sha256(data).hexdigest();old=read(path) if path.exists() else None
        if old:
            if old['request_sha256']!=fingerprint:raise ValueError('resumed request drift')
            if old['status'] in {'response','invalid_response','http_rejected'}:return old
            if old['status']=='in_flight':raise RuntimeError('unresolved in-flight request; inspect process before explicit transport recovery')
            if old['status']=='transport_error' and len(old['events'])>=3:return old
        events=old['events'] if old else []
        record={'request':body,'request_sha256':fingerprint,'endpoint':self.endpoint,'events':events,'status':'prepared',
                'tls_version':'TLSv1.2','certificate_verification':True,'transport_route':'direct_https_to_registered_api_endpoint'}
        for attempt in range(len(events),3):
            started=time.monotonic();event={'attempt':attempt+1,'started_unix':time.time(),'status':'in_flight'}
            events.append(event);record['status']='in_flight';save(path,record)
            try:
                request=Request(self.endpoint,data=data,headers={'Content-Type':'application/json','Authorization':'Bearer '+self.key})
                with urlopen(request,timeout=180,context=self.context) as response:raw=response.read().decode('utf-8')
                record['raw_response_text']=raw
                event.update(status='response',seconds=time.monotonic()-started)
                try:
                    value=json.loads(raw);record['response']=value
                    if not isinstance(value,dict) or not isinstance(value.get('choices'),list):raise ValueError('invalid response envelope')
                    event['usage']=value.get('usage')
                    record['status']='response'
                except (ValueError,TypeError):record['status']='invalid_response'
                save(path,record);return record
            except HTTPError as exc:
                retryable=exc.code==429 or exc.code>=500
                event.update(status='http_error',code=exc.code,seconds=time.monotonic()-started)
                try:
                    detail=exc.read().decode('utf-8',errors='replace')[:4096]
                    event['provider_error_excerpt']=detail.replace(self.key,'[REDACTED]')
                except (OSError,AttributeError):event['provider_error_excerpt_unavailable']=True
                record['status']='transport_error' if retryable else 'http_rejected';save(path,record)
                if not retryable:return record
            except (URLError,TimeoutError,ConnectionError) as exc:
                event.update(status='transport_error',error_type=type(exc).__name__,seconds=time.monotonic()-started)
                cause=getattr(exc,'reason',exc)
                event.update(transport_reason_type=type(cause).__name__,transport_errno=getattr(cause,'errno',None))
                record['status']='transport_error';save(path,record)
            if attempt<2:time.sleep(2**attempt)
        return record

def load_tokenizer(folder,model):
    from transformers import AutoTokenizer
    binding=read(folder/'artifact-binding.json')
    assert binding['model']==model
    assert all(sha(folder/name)==value for name,value in binding['files'].items())
    tokenizer=AutoTokenizer.from_pretrained(str(folder),local_files_only=True)
    def counter(messages):
        return len(tokenizer.apply_chat_template(messages,tokenize=True,add_generation_prompt=True,enable_thinking=False))
    return counter,binding

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--questions',type=Path,required=True);p.add_argument('--question-id',action='append',required=True)
    p.add_argument('--model',choices=['qwen3-8b','qwen3-14b'],required=True)
    p.add_argument('--method',choices=['bm25','e5','hybrid','graph','none'],required=True)
    p.add_argument('--tokenizer',type=Path,required=True);p.add_argument('--proxy-settings',type=Path,required=True)
    p.add_argument('--corpus',type=Path);p.add_argument('--corpus-manifest',type=Path);p.add_argument('--source-map',type=Path)
    p.add_argument('--e5-index',type=Path);p.add_argument('--graph',type=Path)
    p.add_argument('--graph-ablation',choices=['full','no_cross','no_conditions','no_extension'],default='full')
    p.add_argument('--output',type=Path,required=True);p.add_argument('--prepare-only',action='store_true')
    p.add_argument('--tool-calls',type=int,default=8);p.add_argument('--knowledge-characters',type=int,default=24000)
    a=p.parse_args();base,key=settings(a.proxy_settings)
    if a.method!='graph' and a.graph_ablation!='full':raise ValueError('graph ablation requires graph method')
    graph_options={'with_cross':a.graph_ablation!='no_cross','with_conditions':a.graph_ablation!='no_conditions',
                   'with_paths':a.graph_ablation!='no_extension'}
    # Load the private credential before installing the input guard; never save it.
    from chapter2_knowledge_input_guard import install
    guard=install(a.questions)
    questions=read(a.questions)
    if not isinstance(questions,list) or any(set(q)!={'id','question'} or not isinstance(q['id'],str) or not isinstance(q['question'],str) for q in questions):
        raise ValueError('strict id/question production input required')
    ids=[q['id'] for q in questions]
    if len(ids)!=len(set(ids)) or len(a.question_id)!=len(set(a.question_id)) or not set(a.question_id)<=set(ids):raise ValueError('invalid selected question IDs')
    selected=[q for q in questions if q['id'] in a.question_id]
    counter,tokenizer_binding=load_tokenizer(a.tokenizer,a.model)
    kb=KnowledgeBudget(tool_calls=a.tool_calls,total_characters=a.knowledge_characters);mb=ModelBudget()
    artifact_paths={}
    if a.method!='none':
        if not all((a.corpus,a.corpus_manifest,a.source_map)):raise ValueError('retrieval arm requires corpus inputs')
        corpus=FrozenKnowledgeCorpus(a.corpus,a.corpus_manifest)
        artifact_paths={'corpus_manifest':a.corpus_manifest,'source_map':a.source_map}
        assert read(a.source_map)['files']==corpus.hashes,'backend authority map differs from independent manifest'
        if a.method in {'e5','hybrid'}:artifact_paths['e5_manifest']=a.e5_index/'manifest.json'
        if a.method=='graph':artifact_paths['graph']=a.graph
    else:corpus=None
    source_files=[Path(__file__),Path(__file__).parent/'chapter2_qa_backends.py',Path(__file__).parent/'chapter2_knowledge_input_guard.py',
      Path(__file__).parent/'chapter2_qwen_proxy_config.py',PROJECT/'src/principia_core/retrieval/knowledge_qa.py',
      PROJECT/'src/principia_core/retrieval/knowledge_agent.py',Path(__file__).parent/'chapter2_baseline_native.py',
      Path(__file__).parent/'candidate_graph_utils.py',Path(__file__).parent/'candidate_hybrid.py',
      Path(__file__).parent/'chapter2_knowledge_graph_retriever.py']
    protocol={'schema':'autonomous_chapter2_qa_development_v1','model':a.model,'method':a.method,'endpoint':base+'/chat/completions',
      'questions_sha256':sha(a.questions),'selected_ids':[q['id'] for q in selected],'tokenizer':tokenizer_binding,
      'graph_ablation':a.graph_ablation if a.method=='graph' else None,'graph_options':graph_options if a.method=='graph' else None,
      'model_budget':asdict(mb),'knowledge_budget':asdict(kb),'system_prompt':SYSTEM,'input_guard':guard,
      'artifacts_sha256':{name:sha(path) for name,path in artifact_paths.items()},
      'source_sha256':{path.relative_to(PROJECT).as_posix():sha(path) for path in source_files},
      'transport_attempts_max':3,'content_retries':0,'formal_result':False,
      'tls_version':'TLSv1.2','certificate_verification':True,
      'transport_route':'direct_https_to_registered_api_endpoint',
      'transport_circuit':'Stop this arm after a task exhausts same-request transport attempts; remaining selected tasks stay unattempted.',
      'input_token_count':'frozen Qwen chat template, enable_thinking=false; provider usage also preserved'}
    protocol_path=a.output/'protocol.json'
    if protocol_path.exists() and read(protocol_path)!=protocol:raise ValueError('protocol drift; create a new development revision')
    save(protocol_path,protocol)
    for path in source_files:
        dest=a.output/'runtime'/path.relative_to(PROJECT)
        if dest.exists() and sha(dest)!=sha(path):raise ValueError('runtime snapshot drift')
        dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(path.read_bytes())
    if a.prepare_only:print(wire({'status':'prepared','sessions':len(selected)}));return
    if a.method!='none':
        from chapter2_qa_backends import create_backend
        backend=create_backend(a.method,a.corpus,a.source_map,e5_index=a.e5_index,graph=a.graph,graph_options=graph_options)
    else:backend=None
    summaries=[];transport_circuit=False
    for question in selected:
        folder=a.output/'sessions'/question['id'];result_path=folder/'result.json'
        if result_path.exists():result=read(result_path)
        else:
            tools=KnowledgeToolSession(a.method,corpus,backend,kb)
            client=RecordedQwenClient(protocol['endpoint'],key,folder/'requests')
            agent=AutonomousKnowledgeAgent(a.model,tools,client,counter,mb)
            begin=time.monotonic();offset=len(backend.events) if backend else 0
            result=agent.run(question['question'])
            result.update(question=question,protocol_sha256=sha(protocol_path),seconds=time.monotonic()-begin,
               native_ranking_events=backend.events[offset:] if backend else [])
            save(result_path,result)
        summaries.append({'id':question['id'],'status':result['status'],'tool_calls':len(result['tool_events']),
          'knowledge_characters':result['knowledge_characters'],'references_delivered':result.get('references_delivered'),
          'counted_input_tokens':result['counted_input_tokens'],'actual_completion_tokens':result['actual_completion_tokens'],
          'result_sha256':sha(result_path)})
        print(wire(summaries[-1]),flush=True)
        if result['status'] in {'transport_error','http_rejected'}:transport_circuit=True;break
    save(a.output/'summary.json',{'schema':'autonomous_qa_development_summary_v1','formal_result':False,'sessions':summaries,
      'planned_sessions':len(selected),'unattempted_sessions':len(selected)-len(summaries),'transport_circuit_open':transport_circuit})

if __name__=='__main__':main()
