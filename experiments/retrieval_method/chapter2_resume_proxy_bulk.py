"""接续原代理 v7 评分：复用终态、八路并发、单次调用、保留中断未知。"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from threading import Lock

from chapter2_qwen_routing import RecordedProxyQwenClient
from chapter2_local_bounded_execution import run_bounded
from chapter2_local_full_review_gate import source_release_args
from chapter2_billing_resume_controller import exclusive_stage_lock


def read(p): return json.loads(p.read_text(encoding='utf-8-sig'))
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p, value):
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open('x', encoding='utf-8') as f:
        json.dump(value, f, ensure_ascii=False, indent=2)


def recorded_or_new(client, body, turn):
    path = client.folder / f'{turn:02d}.json'
    if not path.exists():
        return client(body, turn)
    record = read(path)
    if record.get('request') != body or record.get('endpoint') != client.deployment.endpoint:
        raise ValueError('Existing request identity differs')
    if record['status'] in {'in_flight', 'prepared'}:
        raise ValueError('Unresolved request must be separately sealed, never reissued')
    if record.get('raw_response') is not None:
        record = dict(record, response=record['raw_response'])
    return record


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--activity', type=Path, required=True)
    p.add_argument('--registration', type=Path, required=True)
    p.add_argument('--settings', type=Path)
    p.add_argument('--execute', action='store_true')
    # Keep the short archive junction on Windows; canonical paths can exceed
    # the process's filesystem path limit for historic amendment filenames.
    a = p.parse_args(); root = a.activity.absolute(); reg = read(a.registration)
    if (reg.get('schema') != 'original_proxy_bulk_resume_v1' or reg.get('answer_workers') != 8
            or reg.get('new_transport_attempts_max') != 1 or reg.get('content_retries') != 0
            or reg.get('reuse_local_scores') is not False or reg.get('rubric_version') != 'source_free_v7'):
        raise ValueError('Invalid proxy continuation registration')
    for name, digest in reg['implementation_sha256'].items():
        if sha(Path(__file__).parent/name) != digest: raise ValueError('Bulk implementation drift: '+name)
    for relative, digest in reg['evidence_sha256'].items():
        if sha(root/relative) != digest: raise ValueError('Bound evidence drift: '+relative)
    matrix = read(root/'setup/local_uniform_judge_001/matrix-preparation.json')
    for mapping in ['input_sha256','legacy_score_bindings_sha256']:
        for relative, digest in matrix[mapping].items():
            if sha(root/relative) != digest: raise ValueError('Frozen input or historical score drift')
    baseline = read(root/reg['baseline_inventory'])
    for relative, digest in baseline['files_sha256'].items():
        if sha(root/relative) != digest: raise ValueError('Proxy baseline drift')
    # Validate the original frozen execution package and complete source release.
    proof = read(root/'audit/complete_source_release_verification_001.json')
    ns = source_release_args(proof)
    package = root/'setup/full_review_grading_execution_003'
    sys.path.insert(0,str(package))
    from guard import validate_package
    manifest = validate_package(package,'controller')
    if sha(package/'manifest.json') != proof['frozen_execution_package_manifest_sha256']:
        raise ValueError('Frozen package drift')
    runtime = Path(manifest['bases']['grading']['runtime'])
    sys.path.insert(0,str(runtime/'src')); sys.path.insert(0,str(runtime/'experiments/retrieval_method'))
    from full_review import verify_complete_release
    reviews, reviewbindings, reviewrows, release = verify_complete_release(ns,persist=False)
    if len(reviews) != 1248: raise ValueError('Complete source review required')
    from chapter2_knowledge_formal_plan import validate_activation, activation_identity, digest
    from chapter2_knowledge_evaluation import verify_setup, verify_dataset, delivered_lines, primary_bounds
    from chapter2_knowledge_formal_review import verify_selection
    plan = read(ns.plan); setup = read(ns.evaluation); activation = read(ns.activation)
    verify_setup(setup,ns.plan); validate_activation(activation,plan,sha(ns.plan))
    verify_dataset(ns.dataset,setup['dataset_seal_sha256'])
    verify_selection(read(ns.review_selection),plan,sha(ns.plan))
    if activation['judge_protocol_sha256'] != setup['accepted_judge_protocol_sha256']:
        raise ValueError('Judge acceptance differs')
    spec = importlib.util.spec_from_file_location('frozen_proxy_grading',package/'grading.py')
    grading = importlib.util.module_from_spec(spec); spec.loader.exec_module(grading)
    if reg['frozen_score_answer_file_sha256'] != sha(package/'grading.py'):
        raise ValueError('Frozen scoring kernel drift')
    schedule = matrix['generated_sessions']
    if len(schedule) != 13536 or len({(i['cell_id'],i['question_id']) for i in schedule}) != 13536:
        raise ValueError('Full fixed matrix required')
    out = root/'formal_scores'; protocols={}; cached={}
    # Derive original per-cell identity before credentials or HTTP.
    endpoint = reg['endpoint']
    for cell in plan['cells']:
        cid = cell['id']
        expected = dict(schema='activated_knowledge_qa_formal_grading_cell_v1',formal_result=True,
            cell_id=cid,plan_sha256=sha(ns.plan),activation_sha256=activation_identity(activation,sha(ns.activation),cid),
            evaluation_sha256=sha(ns.evaluation),endpoint=endpoint,judge_model='qwen3-14b',
            rubric_version='source_free_v7',transport_attempts_max=3,content_retries=0)
        target = out/cid/'protocol.json'
        if target.exists() and read(target) != expected: raise ValueError('Original proxy protocol drift')
        protocols[cid]=(target,expected)
    interrupted = reg['sealed_unresolved_requests_sha256']
    current_unresolved={}
    for path in out.glob('**/requests/*.json'):
        record=read(path)
        if record['status'] in {'in_flight','prepared'}:
            current_unresolved[path.relative_to(root).as_posix()]=sha(path)
    if current_unresolved != interrupted: raise ValueError('Unregistered unresolved proxy attempt')
    for item in schedule:
        cid,qid=item['cell_id'],item['question_id']; path=out/cid/'sessions'/qid/'score.json'
        if path.exists():
            if path.relative_to(root).as_posix() not in baseline['files_sha256']:
                raise ValueError('Unregistered terminal score')
            binding=read(path.parent/'score-binding.json'); score=read(path)
            if (binding != dict(score_sha256=sha(path),result_sha256=item['result_sha256'],
                    protocol_sha256=sha(protocols[cid][0])) or score['result_sha256']!=item['result_sha256']):
                raise ValueError('Historical terminal binding drift')
            primary_bounds(score); cached[(cid,qid)]=score
    if len(cached)!=reg['baseline_terminal_scores']: raise ValueError('Baseline terminal scope differs')
    if not a.execute:
        print(json.dumps(dict(ready=True,total=13536,existing=len(cached),remaining=13536-len(cached),
            source_reviews=len(reviews),network_requests=0)),flush=True); return
    from chapter2_autonomous_qa import load_tokenizer
    from chapter2_answer_scoring import scoring_payload
    from chapter2_partial_answer_scoring import COVERAGE_PROMPT,SOURCE_PROMPT
    from principia_core.retrieval.knowledge_qa import FrozenKnowledgeCorpus
    if setup['judge_settings']['judge_prompt']!={'candidate_only_coverage':COVERAGE_PROMPT,'independent_source_audit':SOURCE_PROMPT}:
        raise ValueError('Accepted frozen prompts drift')
    resources=read(ns.resources)
    corpus=FrozenKnowledgeCorpus(Path(resources['corpus']),Path(resources['corpus_manifest']))
    if sha(Path(resources['corpus_manifest'])) != setup['judge_settings']['corpus_manifest_sha256']:
        raise ValueError('Corpus identity drift')
    annotations={r['id']:r for r in read(ns.dataset/'scoring/annotations.json')}
    evidence=read(ns.dataset/'scoring/evidence.json'); questions={r['id']:r for r in read(ns.dataset/'model/questions.json')}
    rawcount,tokenizer=load_tokenizer(Path(resources['tokenizer_qwen3-14b']),'qwen3-14b')
    if tokenizer != setup['judge_settings']['tokenizer']: raise ValueError('Accepted tokenizer drift')
    countlock=Lock()
    def count(messages):
        with countlock:return rawcount(messages)
    run=root/reg['run_folder']
    with exclusive_stage_lock(out/'billing-resume-controller.lock'):
        if run.exists(): raise FileExistsError('New execution folder required')
        client=RecordedProxyQwenClient('qwen3-14b',run/'unused',a.settings)
        if client.deployment.endpoint!=endpoint: raise ValueError('Proxy config differs from registration')
        for target,expected in protocols.values():
            if not target.exists():save(target,expected)
        save(run/'start.json',dict(registration_sha256=sha(a.registration),utc=datetime.now(timezone.utc).isoformat(),
            baseline=len(cached),planned=13536,provider='qwen_proxy',answer_workers=8))
        statuses=Counter(v['status'] for v in cached.values()); completed=len(cached)
        def work(item):
            cid,qid=item['cell_id'],item['question_id']; key=(cid,qid)
            resultpath=root/'formal_generation/cells'/cid/'sessions'/qid/'result.json'
            if sha(resultpath)!=item['result_sha256']: raise ValueError('Generation result changed')
            result=read(resultpath); folder=out/cid/'sessions'/qid; protocolsha=sha(protocols[cid][0])
            if key in reviewbindings and reviewbindings[key]!=sha(resultpath): raise ValueError('Source review binds other answer')
            binding=dict(question_id=qid,formal_cell_id=cid,formal_result=True,result_sha256=sha(resultpath),
                generation_status=result['status'],protocol_sha256=protocolsha,
                reference_judgment_sha256=digest(reviewrows[key]) if key in reviewrows else None)
            interrupted_here={p:s for p,s in interrupted.items() if p.startswith(folder.relative_to(root).as_posix()+'/requests/')}
            if interrupted_here:
                # Preserve the old raw in-flight record byte for byte. No later
                # stages or replay of the interrupted attempt are permitted.
                value=dict(status='judge_unknown',reason='previous_proxy_client_interrupted',
                    metrics=dict(complete_valid_answer=None,complete_lower=0,complete_upper=1),
                    sealed_unresolved_requests_sha256=interrupted_here,
                    usage_unknown=True,duration_unknown=True,requests_reissued=False)
            else:
                payload=scoring_payload(questions[qid]['question'],annotations[qid],evidence,corpus,
                    result['answer'],delivered_lines(result)) if result['status']=='answered' else None
                answerclient=RecordedProxyQwenClient('qwen3-14b',folder/'requests',a.settings)
                if answerclient.deployment!=client.deployment: raise ValueError('Proxy deployment changed')
                value=grading.score_answer(result,payload,lambda body,turn:recorded_or_new(answerclient,body,turn),count)
            score={**binding,**value,'references_delivered':result.get('references_delivered'),
                'reference_verdict_file_sha256_at_creation':sha(ns.review_verdicts) if key in reviewrows else None,
                'bulk_resume_registration_sha256':sha(a.registration)}
            save(folder/'score.json',score)
            save(folder/'score-binding.json',dict(score_sha256=sha(folder/'score.json'),result_sha256=sha(resultpath),protocol_sha256=protocolsha))
            return score
        def observe(item,score):
            nonlocal completed
            completed+=1; statuses[score['status']]+=1
            if completed%25==0:print(json.dumps(dict(completed=completed,total=13536)),flush=True)
            if score.get('reason') in {'transport_error','http_rejected'}:
                raise RuntimeError('Proxy transport circuit stopped; all admitted work drains; never retry failures')
        stop=run/'STOP'
        def remaining():
            for item in schedule:
                if stop.exists():return
                if (item['cell_id'],item['question_id']) not in cached:yield item
        run_bounded(remaining(),work,observe,8)
        report=dict(schema='original_proxy_bulk_completion_v1',registration_sha256=sha(a.registration),
            completed_scores=completed,planned_scores=13536,full_scope_complete=completed==13536,
            status_counts=dict(statuses),requires_independent_native_terminal_verification=True,
            utc=datetime.now(timezone.utc).isoformat())
        save(run/('completion.json' if completed==13536 else 'stopped.json'),report)
        print(json.dumps(report),flush=True)


if __name__=='__main__':main()
