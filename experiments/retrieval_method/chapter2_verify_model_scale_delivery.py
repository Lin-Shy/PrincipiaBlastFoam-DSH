"""Verify the completed 8B/14B evidence, accepted graph and released manuscript."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from chapter2_optimization_200 import PROJECT, RESOURCES, DATASET, read, sha
from chapter2_metric_revision_200 import graded_validity, valid_at_threshold
from chapter2_model14b_generation_audit import audit_session

W=PROJECT.parent
C=W/'graduation-experiment-results/chapter2_retrieval/current'
M=W/'graduation-thesis-materials/graduation-manuscript'


def main():
    # Preserve the complete 8B verifier, including its 800 true reused baselines.
    subprocess.run([sys.executable,'-X','utf8',str(Path(__file__).with_name('chapter2_verify_revision_delivery_200.py'))],
        cwd=W,check=True,capture_output=True,text=True,encoding='utf-8')
    base=read(C/'cleanup-verification.json')
    r=C/'model14b_200_20261019_002'
    p=read(r/'protocol.json')
    assert p['answer_model']=='qwen3-14b' and p['baseline_reuse'] is False
    assert p['generation_sessions']==1400 and p['max_concurrent_answer_requests']==14
    assert sha(r/'user-authorization.json')==p['authorization_sha256']
    assert read(r/'user-authorization.json')['explicit_data_export_approved']
    assert sha(C/'proxy14b-export-authorization.json')==p['explicit_export_approval_sha256']
    assert p['dataset_binding_sha256']==sha(DATASET/'binding.json')
    assert p['design_sha256']==sha(r/'provenance/adopted-chapter02.md')
    for rel,digest in p['implementation_sha256'].items():
        assert sha(PROJECT/rel)==sha(r/'runtime'/rel)==digest,rel
    for name,digest in p['graphs'].items():
        assert sha(r/'graphs'/(name+'.json'))==digest,name
        assert sha(C/'revision_200_20261019_002/graphs'/(name+'.json'))==digest,name
    assert sha(r/'graphs/manifest.json')==p['graph_manifest_sha256']
    audit=read(r/'generation-audit.json')
    closure=read(r/'recovery/closure.json')
    assert audit['unicode_delivery_closure_sha256']==sha(r/'recovery/closure.json')
    assert audit['registered']==audit['closed']==1400 and audit['answered']==1391
    assert audit['physical_requests']==3151 and audit['request_statuses']=={'response':3151}
    assert audit['executor_concurrency_bound']==14 and audit['network_calls_for_closure']==0
    assert audit['audit_script_sha256']==sha(r/'provenance/delivery-audit-source.py')
    assert closure['network_calls']==closure['answer_text_repairs']==0
    assert len(closure['recovered_sessions'])==2
    for item in closure['recovered_sessions']:
        arm,qid=item['arm'],item['id']
        folder=r/'generation'/arm/qid
        assert sha(folder/'result.serialization-failed.bin')==item['partial_bytes_sha256']
        assert sha(r/'recovery'/arm/(qid+'-consumer-result.json'))==item['preserved_consumer_result_sha256']
        assert sha(folder/'result.json')==item['closed_result_sha256']
        failure=read(folder/'result.json')
        assert failure['status']=='invalid_unicode_output' and not failure['answer']
        assert failure['timing_lower_bound'] and item['network_calls_during_closure']==0
    for key in ['model_budget','knowledge_budget','source_resources','scoring_data_sha256','e5_resources']:
        assert p[key]==read(C/'revision_200_20261019_002/protocol.json')[key],key
    for name,digest in p['source_resources'].items():
        assert sha(RESOURCES/name)==digest,name
    for name,digest in p['scoring_data_sha256'].items():
        assert sha(DATASET/'scoring'/name)==digest,name
    assert sha(RESOURCES/'tokenizers/qwen3-14b/artifact-binding.json')==p['tokenizer_sha256']
    s=r/'scoring_001'
    sp=read(s/'protocol.json');closed=read(s/'completion.json')
    assert sp['model']=='qwen3-14b' and sp['workers']==16 and sp['targeted_reviews_per_answer']==0
    assert closed['sessions']==1400 and closed['execution_protocol_sha256']==sha(s/'protocol.json')
    summary=read(r/'analysis_001/summary.json');rows=read(r/'analysis_001/session-metrics.json')
    assert len(rows)==len({(row['arm'],row['id']) for row in rows})==1400
    assert summary['answer_model']=='qwen3-14b' and summary['judge_same_model_as_answer']
    assert summary['formal_protocol_sha256']==sha(r/'protocol.json')
    assert summary['scoring_completion_sha256']==sha(s/'completion.json')
    assert summary['generation_audit_sha256']==sha(r/'generation-audit.json')
    assert summary['analysis_source_sha256']==sha(r/'analysis_001/analysis-source.py')
    pipeline=read(r/'completion-pipeline-complete.json')
    assert pipeline['completed'] and pipeline['analysis_summary_sha256']==sha(r/'analysis_001/summary.json')
    assert pipeline['source_sha256']==sha(r/'provenance/after-scoring-source.py')
    assert pipeline['generation_audit_sha256']==sha(r/'generation-audit.json')
    assert pipeline['scoring_completion_sha256']==sha(s/'completion.json')
    assert pipeline['local_delivery_closure_sha256']==sha(r/'recovery/closure.json')
    assert summary['analysis_source_sha256']==read(r/'completion-pipeline-protocol.json')['analysis_source_sha256']
    assert sha(r/'provenance/completion-pipeline-source.py')==read(r/'completion-pipeline-protocol.json')['pipeline_source_sha256']
    questions={x['id']:x['question'] for x in read(r/'public-questions.json')}
    cache={}
    for row in rows:
        arm,qid=row['arm'],row['id']
        assert not row['reused']
        g=r/'generation'/arm/qid/'result.json'
        t=s/'sessions'/arm/qid/'result.json'
        assert sha(g)==read(r/'completion'/(arm+'.json'))['results_sha256'][qid]
        assert sha(t)==closed['results_sha256'][arm+'/'+qid]
        assert read(t)['generation_sha256']==sha(g)
        assert audit_session(r,arm,qid,questions[qid],p,cache)['result_sha256']==sha(g)
        assert graded_validity(row)==(row['score_lower'],row['score_upper'])
        assert valid_at_threshold(row,1)==(row['cv_lower'],row['cv_upper'])
    for key,digest in read(r/'analysis_001/judge-request-bindings.json').items():
        arm,qid,number=key.split('/')
        assert sha(s/'sessions'/arm/qid/'requests'/(number+'.json'))==digest,key
    for arm,value in summary['by_arm'].items():
        selected=[row for row in rows if row['arm']==arm]
        assert len(selected)==value['n']==200 and value['condition_n']==100
        for side in ['lower','upper']:
            assert abs(sum(row['score_'+side] for row in selected)/200-value['score_'+side])<1e-12
        assert all(v['n']==50 for v in summary['by_type'][arm].values())
    assets=M/'assets/chapter2/model_scales'
    manifest=read(assets/'source-manifest.json')
    for rel,digest in manifest['input_sha256'].items():
        assert sha(W/rel)==digest,rel
    for name,digest in manifest['outputs_sha256'].items():
        assert sha(assets/name)==digest,name
    plan=read(C/'publication-plan.json');official=read(M/'official_manifest.json')
    assert plan['answer_model_matrix']['qwen3-14b']['status']=='complete'
    assert plan['answer_model_matrix']['qwen3-32b']['status']=='waiting_user_api'
    assert plan['accepted_official_method']['sha256']==sha(r/'graphs/selected.json')
    assert official['review']['completed_answer_models']==['qwen3-8b','qwen3-14b']
    current_paper_sessions=official['review']['full_session_count']
    assert current_paper_sessions in {2800,3200}
    if current_paper_sessions==3200:
        assert plan['basic_search_extension']['status']=='complete'
        assert manifest['main_methods']==6 and manifest['sessions_each']==1600
    assert official['review']['visual_review_status']=='passed'
    result=dict(schema='chapter2_answer_model_scale_delivery_v1',passed=True,
        answer_models_completed=['qwen3-8b','qwen3-14b'],answer_model_pending='qwen3-32b',
        questions=200,sessions_each_model=1400,total_quality_sessions=2800,
        verification_scope='Original two-model seven-arm activities, kept under their original identities',
        current_paper_total_quality_sessions=current_paper_sessions,
        requires_separate_basic_search_verification=current_paper_sessions==3200,
        excluded_local_network_attempt_sessions=1400,all_actual_failures_and_unknowns_retained=True,
        graph_accepted_and_identical=True,source_runtime_bindings_verified=True,
        judge_receipts_14b=len(read(r/'analysis_001/judge-request-bindings.json')),
        generation_audit_14b_sha256=sha(r/'generation-audit.json'),
        analysis_8b_sha256=base['summary_sha256'],analysis_14b_sha256=sha(r/'analysis_001/summary.json'),
        official_pdf_sha256=official['pdf_sha256'],official_manifest_sha256=sha(M/'official_manifest.json'),
        official_pdf_pages=official['review']['pages'],verifier_source_sha256=sha(Path(__file__)))
    (C/'model-scale-delivery-verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':
    main()
