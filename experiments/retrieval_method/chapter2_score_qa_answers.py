"""Development score-side judge runs; production answering never imports gold."""
import argparse
from collections import Counter
import json
from pathlib import Path
import time
from chapter2_autonomous_qa import RecordedQwenClient,load_tokenizer,read,save,sha,PROJECT
from chapter2_qwen_proxy_config import settings
from principia_core.retrieval.knowledge_qa import FrozenKnowledgeCorpus
from chapter2_answer_scoring import scoring_payload,judge_body,parse_judgment,JUDGE_MODEL,JUDGE_PROMPT

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--dataset',type=Path,required=True)
    p.add_argument('--corpus',type=Path,required=True);p.add_argument('--manifest',type=Path,required=True)
    p.add_argument('--results',type=Path,required=True);p.add_argument('--tokenizer',type=Path,required=True)
    p.add_argument('--proxy-settings',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--rubric-version',choices=['literal_v1','segments_v2','structured_v3','staged_v4','reasoning_v5','source_free_v6','source_free_v7','source_scoped_v8'],default='literal_v1')
    a=p.parse_args();base,key=settings(a.proxy_settings);dataset=a.dataset.resolve()
    if a.rubric_version=='source_scoped_v8':
        from chapter2_scoped_answer_scoring import scoped_requests,parse_scoped_judgments,COVERAGE_PROMPT,SOURCE_PROMPT,delivery_scope
        staged_requests=scoped_requests;parse_staged_judgments=parse_scoped_judgments
        prompt={'candidate_only_coverage':COVERAGE_PROMPT,'independent_source_audit':SOURCE_PROMPT}
    elif a.rubric_version=='source_free_v7':
        from chapter2_partial_answer_scoring import source_free_requests,parse_partial_judgments,COVERAGE_PROMPT,SOURCE_PROMPT
        staged_requests=source_free_requests;parse_staged_judgments=parse_partial_judgments
        prompt={'candidate_only_coverage':COVERAGE_PROMPT,'independent_source_audit':SOURCE_PROMPT}
    elif a.rubric_version=='source_free_v6':
        from chapter2_source_free_answer_scoring import source_free_requests,parse_source_free_judgments,COVERAGE_PROMPT,SOURCE_PROMPT
        staged_requests=source_free_requests;parse_staged_judgments=parse_source_free_judgments
        prompt={'candidate_only_coverage':COVERAGE_PROMPT,'independent_source_audit':SOURCE_PROMPT}
    elif a.rubric_version=='reasoning_v5':
        from chapter2_reasoning_answer_scoring import reasoning_requests,parse_reasoning_judgments,COVERAGE_PROMPT,SOURCE_PROMPT
        staged_requests=reasoning_requests;parse_staged_judgments=parse_reasoning_judgments
        prompt={'candidate_only_coverage':COVERAGE_PROMPT,'independent_source_audit':SOURCE_PROMPT}
    elif a.rubric_version=='staged_v4':
        from chapter2_staged_answer_scoring import staged_requests,parse_staged_judgments,POINT_PROMPT,AUDIT_PROMPT
        prompt={'isolated_point':POINT_PROMPT,'independent_source_audit':AUDIT_PROMPT}
    elif a.rubric_version=='structured_v3':
        from chapter2_structured_answer_scoring import structured_judge_body,parse_structured_judgment,STRUCTURED_PROMPT
        make_body=structured_judge_body;parse_score=parse_structured_judgment;prompt=STRUCTURED_PROMPT
    elif a.rubric_version=='segments_v2':
        from chapter2_segment_answer_scoring import segment_judge_body,parse_segment_judgment,SEGMENT_PROMPT
        make_body=segment_judge_body;parse_score=parse_segment_judgment;prompt=SEGMENT_PROMPT
    else:make_body=judge_body;parse_score=parse_judgment;prompt=JUDGE_PROMPT
    seal=read(dataset/'dataset-seal.json')
    # The exact seal layout is checked below; no draft scoring fallback.
    files=seal['files']
    for relative,value in files.items():
        expected=value['sha256'] if isinstance(value,dict) else value
        if sha(dataset/relative)!=expected:raise ValueError('sealed scoring dataset drift')
    annotations={r['id']:r for r in read(dataset/'scoring/annotations.json')}
    questions={r['id']:r['question'] for r in read(dataset/'model/questions.json')};evidence=read(dataset/'scoring/evidence.json')
    corpus=FrozenKnowledgeCorpus(a.corpus,a.manifest);counter,tokenizer=load_tokenizer(a.tokenizer,JUDGE_MODEL)
    if a.rubric_version=='reasoning_v5':
        from chapter2_reasoning_answer_scoring import load_reasoning_counter
        counter=load_reasoning_counter(a.tokenizer)
    results=sorted(a.results.glob('**/sessions/*/result.json'))
    if not results:raise ValueError('no QA results for development scoring')
    sources=[Path(__file__),Path(__file__).parent/'chapter2_answer_scoring.py',Path(__file__).parent/'chapter2_autonomous_qa.py',
      Path(__file__).parent/'chapter2_qwen_proxy_config.py',PROJECT/'src/principia_core/retrieval/knowledge_qa.py',
      PROJECT/'src/principia_core/retrieval/knowledge_agent.py']
    if a.rubric_version=='segments_v2':sources.append(Path(__file__).parent/'chapter2_segment_answer_scoring.py')
    if a.rubric_version=='structured_v3':sources.extend([Path(__file__).parent/'chapter2_structured_answer_scoring.py',Path(__file__).parent/'chapter2_segment_answer_scoring.py'])
    if a.rubric_version=='staged_v4':sources.extend([Path(__file__).parent/'chapter2_staged_answer_scoring.py',Path(__file__).parent/'chapter2_segment_answer_scoring.py'])
    if a.rubric_version=='reasoning_v5':sources.extend([Path(__file__).parent/'chapter2_reasoning_answer_scoring.py',Path(__file__).parent/'chapter2_segment_answer_scoring.py'])
    if a.rubric_version=='source_free_v6':sources.extend([Path(__file__).parent/'chapter2_source_free_answer_scoring.py',Path(__file__).parent/'chapter2_reasoning_answer_scoring.py',Path(__file__).parent/'chapter2_segment_answer_scoring.py'])
    if a.rubric_version=='source_free_v7':sources.extend([Path(__file__).parent/'chapter2_partial_answer_scoring.py',Path(__file__).parent/'chapter2_source_free_answer_scoring.py',Path(__file__).parent/'chapter2_reasoning_answer_scoring.py',Path(__file__).parent/'chapter2_segment_answer_scoring.py'])
    if a.rubric_version=='source_scoped_v8':sources.extend([Path(__file__).parent/name for name in ['chapter2_scoped_answer_scoring.py','chapter2_partial_answer_scoring.py','chapter2_source_free_answer_scoring.py','chapter2_reasoning_answer_scoring.py','chapter2_segment_answer_scoring.py']])
    protocol={'schema':'blinded_development_qa_scoring_v1','purpose':'scoring_only','formal_result':False,
      'judge_model':JUDGE_MODEL,'judge_prompt':prompt,'rubric_version':a.rubric_version,'dataset_seal_sha256':sha(dataset/'dataset-seal.json'),
      'corpus_manifest_sha256':corpus.manifest_sha256,'tokenizer':tokenizer,'input_limit':32768,'output_limit':4096,
      'result_bindings':{p.relative_to(a.results).as_posix():sha(p) for p in results},
      'source_sha256':{p.relative_to(PROJECT).as_posix():sha(p) for p in sources},
      'failure_policy':'generation failure is an observed task failure; judge failure is unknown; no content retries',
      'transport_attempts_max':3,'content_retries':0,
      'tls_version':'TLSv1.2','certificate_verification':True,
      'transport_route':'direct_https_to_registered_api_endpoint',
      'transport_circuit':'Stop the batch after one logical judge request exhausts transport attempts; unattempted scores remain pending.',
      'primary_candidate':'complete_valid_answer; quality, coverage, applicability and failure types reported separately'}
    protocol['additional_material_policy']='Necessary score-side original spans plus deduplicated actually delivered original lines, without arm/rank/tool labels; gold is not exhaustive truth.'
    if a.rubric_version in {'staged_v4','reasoning_v5','source_free_v6','source_free_v7','source_scoped_v8'}:
        protocol['stage_policy']='One fixed isolated request per required point plus one source/condition audit without reference claims; all requests built before any response. No quality retries or voting.'
        protocol['point_output_limit']=1400;protocol['critical_error_labels_assessed']=False
    if a.rubric_version=='reasoning_v5':
        protocol.update(output_limit=8192,point_output_limit=8192,enable_thinking=True,
          stage_policy='One candidate-only entailment request per point, no original sources; then one independent original truth/condition audit without reference claims. Fixed requests, no quality retry.',
          input_count_limit='Frozen Qwen chat-template count with enable_thinking=true; provider usage retained separately.')
    if a.rubric_version in {'source_free_v6','source_free_v7','source_scoped_v8'}:
        protocol.update(point_output_limit=4096,enable_thinking=False,
          stage_policy='One candidate-only entailment request per point, no original sources; then one independent original truth/condition audit without reference claims. Registered non-thinking model. Fixed requests, no quality retry.')
    if a.rubric_version in {'source_free_v7','source_scoped_v8'}:
        protocol['partial_judgment_policy']='A strictly validated necessary-point failure retains complete=0 when a later source/condition dimension is unparseable; preserve unknown dimensions and partial status, no semantic repair.'
    if a.rubric_version=='source_scoped_v8':
        protocol['scope_policy']='Require correct professional subclaims for partial coverage; audit attributed source differences and exact candidate delivery scope separately from necessary score-side originals. No candidate-ID-specific rules.'
    path=a.output/'protocol.json'
    if path.exists() and read(path)!=protocol:raise ValueError('scoring protocol drift; new revision required')
    save(path,protocol)
    for f in sources:
        target=a.output/'runtime'/f.relative_to(PROJECT);target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(f.read_bytes())
    scores=[];transport_circuit=False
    for result_path in results:
        relative=result_path.relative_to(a.results).as_posix();result=read(result_path);qid=result['question']['id']
        if result['question']['question']!=questions[qid]:raise ValueError('answer question does not match sealed scoring question')
        import hashlib
        folder=a.output/'sessions'/hashlib.sha256(relative.encode('utf-8')).hexdigest()[:24];target=folder/'score.json'
        if target.exists():score=read(target)
        else:
            score={'question_id':qid,'result_relative_path':relative,'result_sha256':sha(result_path),'generation_status':result['status'],
              'protocol_sha256':sha(path),'references_delivered':result.get('references_delivered')}
            if result['status']!='answered':
                score.update(status='generation_failed',reason=result['status'],metrics={'complete_valid_answer':0,'complete_lower':0,'complete_upper':0})
            else:
                delivered=[line for e in result.get('tool_events',[]) for line in e.get('delivered_original_lines',[])]
                payload=scoring_payload(questions[qid],annotations[qid],evidence,corpus,result['answer'],delivered)
                if a.rubric_version=='source_scoped_v8' and 'tool_events' in result:
                    payload['delivery_scope']=delivery_scope(corpus,delivered)
                if a.rubric_version in {'staged_v4','reasoning_v5','source_free_v6','source_free_v7','source_scoped_v8'}:
                    requests=staged_requests(payload);counts=[counter(r['body']['messages']) for r in requests]
                    score['planned_counted_input_tokens']=sum(counts);score['stage_input_tokens']=counts
                    if any(c>32768 for c in counts):score.update(status='judge_unknown',reason='judge_input_budget_exhausted',counted_input_tokens=0)
                    else:
                        started=time.monotonic();responses=[];client=RecordedQwenClient(base+'/chat/completions',key,folder/'requests')
                        for index,request in enumerate(requests):
                            response=client(request['body'],index);responses.append(response)
                            if response['status'] in {'transport_error','http_rejected'}:break
                        score['counted_input_tokens']=sum(counts[:len(responses)])
                        if responses[-1]['status'] in {'transport_error','http_rejected'}:score.update(status='judge_unknown',reason=responses[-1]['status'])
                        else:score.update(parse_staged_judgments(responses,payload))
                        score['seconds']=time.monotonic()-started
                else:
                    body=make_body(payload);count=counter(body['messages']);score['counted_input_tokens']=count
                    if count>32768:score.update(status='judge_unknown',reason='judge_input_budget_exhausted')
                    else:
                        started=time.monotonic();response=RecordedQwenClient(base+'/chat/completions',key,folder/'requests')(body,0)
                        score.update(parse_score(response,payload));score['seconds']=time.monotonic()-started
                if score['status']=='judge_unknown':score['metrics']={'complete_valid_answer':None,'complete_lower':0,'complete_upper':1}
            save(target,score)
        scores.append(score);print(json.dumps({k:score.get(k) for k in ('question_id','status','reason','metrics')},ensure_ascii=False),flush=True)
        if score['status']=='judge_unknown' and score.get('reason') in {'transport_error','http_rejected'}:
            transport_circuit=True;break
    save(a.output/'summary.json',{'schema':'development_qa_score_summary_v1','formal_result':False,
      'status_counts':dict(Counter(s['status'] for s in scores)),'scores':scores,
      'planned_scores':len(results),'unattempted_scores':len(results)-len(scores),'transport_circuit_open':transport_circuit})

if __name__=='__main__':main()
