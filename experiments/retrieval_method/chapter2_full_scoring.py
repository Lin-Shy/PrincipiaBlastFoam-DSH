"""Original v7 scoring for the new complete activity, retaining all failures."""
import argparse
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import sys
from threading import RLock

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(PROJECT/'src'))
from chapter2_v2_retrieval_probe import read, save, sha
from chapter2_full_protocol import validate, verify_sources, verify_dataset, verify_result
from chapter2_full_review import verify_selection, load_reviews
from chapter2_proxy_model_execution import run_per_model


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('plan','resources','dataset','generation','selection','reviews','output','receipt','proxy-settings'):
        parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--continue-unattempted',action='store_true')
    parser.add_argument('--timeout',type=int,default=180)
    args=parser.parse_args()
    if args.receipt.exists():raise FileExistsError('New immutable grading receipt required')
    plan=read(args.plan);validate(plan);verify_sources(plan,PROJECT);plan_sha=sha(args.plan)
    verify_dataset(args.dataset,plan['dataset_seal_sha256'])
    selection=verify_selection(read(args.selection),plan,plan_sha)
    review,citations,review_provenance=load_reviews(args.reviews,plan,plan_sha,args.generation,args.selection)
    selected={(r['cell_id'],r['question_id']) for r in selection['cases']}
    from chapter2_autonomous_qa import load_tokenizer
    from chapter2_qwen_routing import routed_client
    from chapter2_v2_development_runner import DeploymentResponse,token_counter
    from chapter2_score_knowledge_formal import score_answer
    from chapter2_partial_answer_scoring import COVERAGE_PROMPT,SOURCE_PROMPT
    from chapter2_answer_scoring import scoring_payload
    from chapter2_knowledge_evaluation import delivered_lines,primary_bounds
    from principia_core.retrieval.knowledge_qa import FrozenKnowledgeCorpus
    resources=read(args.resources)
    if sha(Path(resources['corpus_manifest']))!=plan['artifacts_sha256']['corpus_manifest']:raise ValueError('Scoring corpus changed')
    corpus=FrozenKnowledgeCorpus(resources['corpus'],resources['corpus_manifest'])
    annotations={r['id']:r for r in read(args.dataset/'scoring/annotations.json')}
    evidence=read(args.dataset/'scoring/evidence.json')
    questions={r['id']:r for r in read(args.dataset/'model/questions.json')}
    raw,tokenizer=load_tokenizer(Path(resources['tokenizer_qwen3-14b']),'qwen3-14b');lock=RLock()
    def count(messages):
        with lock:return raw(messages)
    counter=token_counter(count,'bulk')
    value=dict(schema='complete_original_v7_scoring_v4',formal_result=True,plan_sha256=plan_sha,
        selection_sha256=sha(args.selection),dataset_seal_sha256=plan['dataset_seal_sha256'],
        coverage_prompt=COVERAGE_PROMPT,source_prompt=SOURCE_PROMPT,judge_model='qwen3-14b',
        tokenizer=tokenizer,workload='bulk',workers_per_model=16,transport_attempts=1,content_retries=0,
        rubric_version='source_free_v7',source_sha256=plan['runtime_source_sha256'],
        source_first_selected_cases=True,independent_human_truth=False)
    protocol_path=args.output/'protocol.json'
    if protocol_path.exists():
        if read(protocol_path)!=value:raise ValueError('Existing grading protocol changed')
    else:save(protocol_path,value)
    protocol_sha=sha(protocol_path)
    jobs=[];existing=[];pending_review=[];generation_protocols={}
    for cell in plan['cells']:
        diagnostic=cell['kind']=='complete_material'
        gprotocol=args.generation/('diagnostic-protocol.json' if diagnostic else 'protocol.json')
        if read(gprotocol)['plan_sha256']!=plan_sha:raise ValueError('Generation belongs to another formal activity')
        gsha=generation_protocols.setdefault(str(gprotocol),sha(gprotocol))
        for qid in cell['question_ids']:
            result_path=args.generation/cell['id']/'sessions'/qid/'result.json'
            # All generation must close before any new judge phase starts.
            result=verify_result(result_path,questions[qid],cell['id'],gsha)
            index=(cell['id'],qid);folder=args.output/cell['id']/'sessions'/qid
            reference=review_provenance.get(index)
            if index in selected and index not in review:
                if (folder/'score.json').exists():raise ValueError('Selected score lacks preceding source/citation review')
                pending_review.append(dict(cell_id=cell['id'],question_id=qid));continue
            binding=dict(formal_result=True,formal_cell_id=cell['id'],question_id=qid,result_sha256=sha(result_path),
                generation_status=result['status'],protocol_sha256=protocol_sha,reference_provenance=reference)
            if (folder/'score.json').exists():
                score=read(folder/'score.json')
                if any(score.get(k)!=v for k,v in binding.items()) or read(folder/'score-binding.json')!=dict(
                        score_sha256=sha(folder/'score.json'),result_sha256=sha(result_path),protocol_sha256=protocol_sha):
                    raise ValueError('Existing score integrity changed')
                primary_bounds(score);existing.append(score)
            else:
                if (folder/'requests').exists() and any((folder/'requests').iterdir()):raise ValueError('Orphan judge request requires reconciliation')
                jobs.append(dict(cell=cell,id=qid,binding=binding,result_path=result_path))
    if existing and not args.continue_unattempted:raise ValueError('Explicit continuation required; no failed request will be reissued')
    save(args.receipt/'start.json',dict(created_utc=datetime.now(timezone.utc).isoformat(),plan_sha256=plan_sha,
        protocol_sha256=protocol_sha,planned=17136,existing_scores=len(existing),new_unattempted=len(jobs),
        pending_review=pending_review,reviewed_cases=len(review),physical_requests_reissued=False))
    statuses=Counter(r['status'] for r in existing)
    def worker(item):
        cell,qid=item['cell'],item['id'];result=read(item['result_path'])
        payload=scoring_payload(questions[qid]['question'],annotations[qid],evidence,corpus,result['answer'],delivered_lines(result)) if result['status']=='answered' else None
        folder=args.output/cell['id']/'sessions'/qid
        client=DeploymentResponse(routed_client('qwen3-14b',folder/'requests',workload='bulk',settings_path=args.proxy_settings,timeout=args.timeout),'qwen3-14b')
        score={**item['binding'],**score_answer(result,payload,client,counter),'group':annotations[qid]['split_group'],
            'model':cell['model'],'method':cell['method'],'repeat':cell['repeat'],
            'independent_primary':review.get((cell['id'],qid),{}).get('complete_valid_answer'),
            'citation_metrics':citations.get((cell['id'],qid))}
        save(folder/'score.json',score)
        save(folder/'score-binding.json',dict(score_sha256=sha(folder/'score.json'),result_sha256=sha(item['result_path']),protocol_sha256=protocol_sha))
        return score
    def observe(item,score):
        statuses[score['status']]+=1
        print(dict(scored=sum(statuses.values()),planned=17136,status=score['status']),flush=True)
        if score.get('generation_status')=='answered' and score.get('reason') in {'transport_error','http_rejected'}:
            raise RuntimeError('Judge circuit: stop admissions, drain and retain all failures')
    try:run_per_model(jobs,worker,observe,model_of=lambda row:'qwen3-14b',workers_per_model=16)
    except Exception:
        save(args.receipt/'stopped.json',dict(planned=17136,scored=sum(statuses.values()),statuses=dict(statuses),pending_review=pending_review))
        raise
    save(args.receipt/'completion.json',dict(complete=sum(statuses.values())==17136,planned=17136,
        completed=sum(statuses.values()),statuses=dict(statuses),pending_review=pending_review,protocol_sha256=protocol_sha))


if __name__=='__main__':main()
