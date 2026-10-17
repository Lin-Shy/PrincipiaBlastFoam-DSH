"""Continue only unattempted development scores; copy terminal scores verbatim."""
import argparse
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path
import shutil
import sys
from threading import RLock

PROJECT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(PROJECT/'src'))
from chapter2_v2_retrieval_probe import read,save,sha
from chapter2_proxy_model_execution import run_per_model


def partition(input_root,source,protocol):
    jobs=[];existing=[]
    for model in protocol['models']:
        for method in protocol['methods']:
            for qid in protocol['question_ids']:
                rp=input_root/'sessions'/model/method/qid/'result.json'
                folder=source/'sessions'/model/method/qid;sp=folder/'score.json'
                if sp.exists():
                    score=read(sp)
                    if score['result_sha256']!=sha(rp) or (score['model'],score['method'],score['id'])!=(model,method,qid):
                        raise ValueError('Existing score binds another observation')
                    existing.append((model,method,qid,sp,score))
                else:
                    if (folder/'requests').exists() and any((folder/'requests').iterdir()):raise ValueError('Orphan judge request must be reconciled without replay')
                    jobs.append(dict(model=model,method=method,id=qid,result_path=rp))
    return jobs,existing


def verify_availability(path,now=None):
    from chapter2_exact_judge_reuse import request_sha
    row=read(path);raw=row.get('raw_response',{})
    age=((datetime.now(timezone.utc) if now is None else now)-datetime.fromisoformat(row['started_utc'])).total_seconds()
    if (row.get('provider')!='qwen_proxy' or row.get('status')!='response' or row.get('model')!='qwen3-14b'
            or row.get('request',{}).get('model')!='qwen3-14b' or row.get('request_sha256')!=request_sha(row.get('request',{}))
            or raw.get('model')!='qwen3-14b' or not 0<=age<=600):raise ValueError('Fresh exact-model proxy availability required')
    return row['endpoint']


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('input','source','output','dataset','resources','availability'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--timeout',type=int,default=180)
    args=parser.parse_args()
    if args.output.exists():raise FileExistsError('New immutable score continuation required')
    from chapter2_qwen_routing import routed_client
    from chapter2_autonomous_qa import load_tokenizer
    from chapter2_v2_development_runner import DeploymentResponse,token_counter
    from chapter2_score_knowledge_formal import score_answer
    from chapter2_answer_scoring import scoring_payload
    from chapter2_knowledge_evaluation import delivered_lines,primary_bounds
    from principia_core.retrieval.knowledge_qa import FrozenKnowledgeCorpus
    generation=read(args.input/'protocol.json');closed=read(args.input/'completion.json');old=read(args.source/'protocol.json');stopped=read(args.source/'stopped.json')
    if not closed['complete'] or old['workload']!='bulk' or old['generation_protocol_sha256']!=sha(args.input/'protocol.json'):
        raise ValueError('Closed identical bulk development generation required')
    if not set(generation['question_ids'])<=set(read(args.dataset/'split.json')['ids']['dev']):raise ValueError('Development only')
    for key,name in [('annotations_sha256','scoring/annotations.json'),('evidence_sha256','scoring/evidence.json')]:
        if old[key]!=sha(args.dataset/name):raise ValueError('Original scoring rubric changed')
    endpoint=verify_availability(args.availability)
    jobs,existing=partition(args.input,args.source,generation)
    if len(existing)!=stopped['completed'] or len(jobs)+len(existing)!=stopped['planned']:
        raise ValueError('Stopped cohort accounting changed')
    protocol={**old,'schema':'development_v7_unattempted_continuation_v4',
        'scoring_driver_sha256':sha(Path(__file__)),'source_protocol_sha256':sha(args.source/'protocol.json'),
        'source_stopped_sha256':sha(args.source/'stopped.json'),'availability_receipt_sha256':sha(args.availability),
        'created_utc':datetime.now(timezone.utc).isoformat(),'workers_per_model':16,
        'copied_terminal_scores':len(existing),'new_unattempted_scores':len(jobs),
        'policy':'Terminal score files copied byte-for-byte with origin references, including failures/unknown. Only never-attempted jobs create requests.'}
    save(args.output/'protocol.json',protocol)
    statuses=Counter()
    for model,method,qid,path,score in existing:
        primary_bounds(score)
        folder=args.output/'sessions'/model/method/qid;folder.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(path,folder/'score.json')
        if sha(path)!=sha(folder/'score.json'):raise ValueError('Terminal score copy changed bytes')
        save(folder/'source-score-reference.json',dict(source_score=str(path),source_score_sha256=sha(path),new_physical_requests=0))
        statuses[score['status']]+=1
    resources=read(args.resources);corpus=FrozenKnowledgeCorpus(resources['corpus'],resources['corpus_manifest'])
    annotations={r['id']:r for r in read(args.dataset/'scoring/annotations.json')};evidence=read(args.dataset/'scoring/evidence.json')
    questions={r['id']:r['question'] for r in read(args.dataset/'model/questions.json')}
    raw,tokenizer=load_tokenizer(Path(resources['tokenizer_qwen3-14b']),'qwen3-14b')
    if tokenizer!=old['tokenizer']:raise ValueError('Original judge tokenizer changed')
    lock=RLock()
    def count(messages):
        with lock:return raw(messages)
    counter=token_counter(count,'bulk')
    def worker(item):
        model,method,qid=item['model'],item['method'],item['id'];result=read(item['result_path'])
        if result['question']!={'id':qid,'question':questions[qid]}:raise ValueError('Original question changed')
        folder=args.output/'sessions'/model/method/qid
        base=routed_client('qwen3-14b',folder/'requests',workload='bulk',timeout=args.timeout)
        if base.deployment.endpoint!=endpoint:raise ValueError('Availability and scoring deployment differ')
        payload=scoring_payload(questions[qid],annotations[qid],evidence,corpus,result['answer'],delivered_lines(result)) if result['status']=='answered' else None
        value=score_answer(result,payload,DeploymentResponse(base,'qwen3-14b'),counter)
        value.update(result_sha256=sha(item['result_path']),generation_status=result['status'],model=model,method=method,id=qid,
            group=annotations[qid]['split_group'],formal_result=False,continuation_protocol_sha256=sha(args.output/'protocol.json'))
        save(folder/'score.json',value);return value
    def observe(item,value):
        statuses[value['status']]+=1
        print(dict(scored=sum(statuses.values()),planned=stopped['planned'],status=value['status']),flush=True)
        if value.get('generation_status')=='answered' and value.get('reason') in {'transport_error','http_rejected'}:
            raise RuntimeError('New transport circuit: preserve terminal results and drain without replay')
    try:run_per_model(jobs,worker,observe,model_of=lambda row:'qwen3-14b',workers_per_model=16)
    except Exception:
        save(args.output/'stopped.json',dict(planned=stopped['planned'],completed=sum(statuses.values()),statuses=dict(statuses)))
        raise
    save(args.output/'completion.json',dict(complete=True,planned=stopped['planned'],completed=sum(statuses.values()),statuses=dict(statuses)))


if __name__=='__main__':main()
