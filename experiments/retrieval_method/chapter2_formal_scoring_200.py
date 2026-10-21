"""Immutable orchestration of the already frozen, calibrated 200-question rubric."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
import random
from chapter2_optimization_200 import PROJECT, RESOURCES, DATASET, read, save, sha
from chapter2_judge_200 import call_once
from chapter2_judge_200_rubric import requests, parse
from chapter2_answer_scoring import scoring_payload
from chapter2_autonomous_qa import load_tokenizer
from chapter2_qwen_routing import routed_client
from principia_core.retrieval.knowledge_qa import FrozenKnowledgeCorpus


def unidentified(reason):
    return dict(status='judge_unknown', reason=reason, metrics=dict(
        required_point_coverage_lower=0, required_point_coverage_upper=1,
        complete_valid_answer=None, complete_lower=0, complete_upper=1,
        factuality='unknown', applicability='unknown'))


def failed_generation(status):
    return dict(status='generation_failed', reason=status, metrics=dict(
        required_point_coverage_lower=0, required_point_coverage_upper=0,
        complete_valid_answer=0, complete_lower=0, complete_upper=0,
        factuality='not_evaluated', applicability='generation_failed'))


def prepare(root, out):
    if out.exists(): raise FileExistsError(out)
    protocol=read(root/'protocol.json'); audit=read(root/'generation-audit.json')
    if audit['answers_jsonl_sha256']!=sha(root/'answers.jsonl'): raise ValueError('Answer export drift')
    calibration=Path(protocol['judge']['calibration'])
    if sha(calibration/'completion.json')!=protocol['judge']['calibration_completion_sha256'] or not read(calibration/'completion.json')['calibration_passed']:
        raise ValueError('Calibration not bound/passed')
    for rel,digest in protocol['implementation_sha256'].items():
        if sha(PROJECT/rel)!=digest: raise ValueError('Frozen source drift: '+rel)
    for name,digest in protocol['scoring_data_sha256'].items():
        if sha(DATASET/'scoring'/name)!=digest: raise ValueError('Scoring data drift')
    counter,binding=load_tokenizer(RESOURCES/'tokenizers/qwen3-14b','qwen3-14b')
    qs={r['id']:r['question'] for r in read(DATASET/'model/questions.json')}
    anns={r['id']:r for r in read(DATASET/'scoring/annotations.json')}
    evidence=read(DATASET/'scoring/evidence.json')
    corpus=FrozenKnowledgeCorpus(RESOURCES/'corpus',RESOURCES/'corpus-manifest.json')
    rows=[]
    for arm in protocol['arms']:
        for qid in qs:
            source=root/'generation'/arm/qid/'result.json'; result=read(source)
            key=f'{arm}/{qid}'
            row=dict(key=key,arm=arm,id=qid,generation_sha256=sha(source),generation_status=result['status'])
            if result['status']=='answered':
                payload=scoring_payload(qs[qid],anns[qid],evidence,corpus,result['answer'],result['delivered_lines'])
                path=out/'payloads'/arm/(qid+'.json'); save(path,payload)
                row.update(payload_sha256=sha(path), input_tokens=[counter(r['body']['messages']) for r in requests(payload)])
            rows.append(row)
    random.Random(20261019).shuffle(rows)
    source=Path(__file__); target=out/'runtime'/source.name
    target.parent.mkdir(parents=True,exist_ok=True); target.write_bytes(source.read_bytes())
    execution=dict(schema='formal_200_score_execution_v1', formal_protocol_sha256=sha(root/'protocol.json'),
        generation_audit_sha256=sha(root/'generation-audit.json'), answers_sha256=sha(root/'answers.jsonl'),
        calibration_completion_sha256=sha(calibration/'completion.json'), workers=16, seed=20261019,
        model='qwen3-14b',provider='qwen_proxy',workload='bulk',max_transport_attempts=1,content_retries=0,
        targeted_reviews_per_answer=0,input_tokens_per_request=32768,output_tokens_per_request=4096,
        over_limit='No export or trimming; entire answer judge unknown, preserve denominator',
        failure='Generation failure contributes zero; judge unknown contributes lower=0 upper=1 unless frozen parser proves a failure',
        anonymity='Only natural question, anonymous answer, source originals and frozen rubric; no arm/id/model labels in API input',
        authorization='User authorized proxy 14B calibration/scoring/at most one targeted review, and now requests all scoring and thesis results; protocol uses zero reviews',
        tokenizer_binding=binding,tokenizer_binding_sha256=sha(RESOURCES/'tokenizers/qwen3-14b/artifact-binding.json'),
        driver_sha256=sha(source), frozen_implementation_sha256=protocol['implementation_sha256'], sessions=rows,
        statistics_execution=dict(bootstrap_replicates=10000,seed=20261019,
            sign_randomization='All 2^24 group sign assignments, two sided absolute mean paired question difference',
            unknowns='Report sharp marginal lower/upper rates and effect bounds. Conservative tests maximize two-sided p over interval contribution by upper-bound sign tail; no superiority claim if not identified.',
            confidence='Percentile cluster bootstrap, same sampled groups for all arms; both lower and upper endpoint intervals',
            group_macro='Equal weights for 24 pre-existing knowledge groups; question micro retains question weights'))
    save(out/'protocol.json',execution)
    print(json.dumps(dict(sessions=len(rows),answered=sum(r['generation_status']=='answered' for r in rows),
        requests=sum(len(r.get('input_tokens',[])) for r in rows),over_limit=sum(max(r.get('input_tokens',[0]))>32768 for r in rows))),flush=True)


def run(root,out):
    p=read(out/'protocol.json')
    if sha(Path(__file__))!=p['driver_sha256'] or sha(root/'protocol.json')!=p['formal_protocol_sha256']:
        raise ValueError('Execution source/protocol drift')
    for rel,digest in p['frozen_implementation_sha256'].items():
        if sha(PROJECT/rel)!=digest: raise ValueError('Frozen source drift')
    def worker(row):
        folder=out/'sessions'/row['arm']/row['id']; result_path=folder/'result.json'
        if result_path.exists():
            value=read(result_path)
            if value['execution_protocol_sha256']!=sha(out/'protocol.json'):raise ValueError('Result protocol drift')
            return value
        if sha(root/'generation'/row['arm']/row['id']/'result.json')!=row['generation_sha256']: raise ValueError('Answer drift')
        if row['generation_status']!='answered': result=failed_generation(row['generation_status'])
        elif max(row['input_tokens'])>p['input_tokens_per_request']: result=unidentified('judge_input_budget_exceeded_before_export')
        else:
            path=out/'payloads'/row['arm']/(row['id']+'.json')
            if sha(path)!=row['payload_sha256']: raise ValueError('Payload drift')
            payload=read(path); client=routed_client('qwen3-14b',folder/'requests',workload='bulk',timeout=180)
            records=[call_once(client,r['body'],i) for i,r in enumerate(requests(payload))]
            result=parse(records,payload)
            if 'metrics' not in result:result={**unidentified(result.get('reason','unparseable')),**result}
        result.update(arm=row['arm'],id=row['id'],generation_sha256=row['generation_sha256'],
            execution_protocol_sha256=sha(out/'protocol.json'))
        save(result_path,result);return result
    results=[]
    with ThreadPoolExecutor(max_workers=p['workers']) as pool:
        futures=[pool.submit(worker,row) for row in p['sessions']]
        for future in as_completed(futures):
            results.append(future.result())
            if len(results)%20==0:print(json.dumps(dict(closed=len(results),statuses=dict(Counter(r['status'] for r in results)))),flush=True)
    completion=dict(sessions=len(results),statuses=dict(Counter(r['status'] for r in results)),
        execution_protocol_sha256=sha(out/'protocol.json'),
        results_sha256={f"{r['arm']}/{r['id']}":sha(out/'sessions'/r['arm']/r['id']/'result.json') for r in results})
    save(out/'completion.json',completion);print(json.dumps(completion['statuses']),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('command',choices=['prepare','run'])
    parser.add_argument('--root',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();(prepare if args.command=='prepare' else run)(args.root,args.output)
