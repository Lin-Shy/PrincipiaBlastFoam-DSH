"""Verify the six-method extension, original evidence, and official paper."""
from collections import Counter
import hashlib
import json
from pathlib import Path
from chapter2_optimization_200 import PROJECT, read, sha, save
from chapter2_basic_search_200 import verify
from chapter2_metric_revision_200 import graded_validity,valid_at_threshold
from chapter2_revision_analysis_200 import holm

W=PROJECT.parent
C=W/'graduation-experiment-results/chapter2_retrieval/current'
R=C/'basic_search_200_20261019_001'
M=W/'graduation-thesis-materials/graduation-manuscript'
EXPECTED_ORIGINAL={
    'qwen3-8b':('revision_200_20261019_002','a860a2c9f3b7111f60de67877dde8ecfb708b5ec6d9dbd6ba12b81d6b01cc296'),
    'qwen3-14b':('model14b_200_20261019_002','2981cdbb61c2a04bb27f88dc512bcfcb7a4912e2f1a067ed729bee831117d70c')}


def main():
    import runpy
    # Preserve the completed 8B verifier's original 1400-session scope.
    runpy.run_path(str(Path(__file__).with_name('chapter2_verify_revision_delivery_200.py')))
    approval=read(R/'explicit-export-authorization.json')
    assert approval['user_approval_received'] and approval['total_answer_sessions']==400
    assert approval['destination']=='https://api.sqhtoken.com/v1/chat/completions'
    finished=read(R/'completion.json');assert finished['completed'] and finished['new_sessions']==400
    models={}
    for model,(original_name,digest) in EXPECTED_ORIGINAL.items():
        root=R/model;p=verify(root);original=C/original_name
        assert sha(root/'provenance/adopted-chapter02.md')==p['design_sha256']
        assert sha(W/'graduation-datasets/chapter02_knowledge_qa/formal_v2_200/binding.json')==p['dataset_binding_sha256']
        assert sha(original/'analysis_001/summary.json')==digest
        old_protocol=read(original/'protocol.json')
        for rel,d in old_protocol['implementation_sha256'].items():
            assert sha(PROJECT/rel)==sha(original/'runtime'/rel)==d
        if model=='qwen3-14b':
            original_scores=original/'scoring_001'
            original_execution=read(original_scores/'protocol.json')
            original_closed=read(original_scores/'completion.json')
            for session in original_execution['sessions']:
                key=session['arm']+'/'+session['id']
                assert sha(original/'generation'/key/'result.json')==session['generation_sha256']
                assert sha(original_scores/'sessions'/key/'result.json')==original_closed['results_sha256'][key]
            for key,d in read(original/'analysis_001/judge-request-bindings.json').items():
                arm,qid,seq=key.split('/')
                assert sha(original_scores/'sessions'/arm/qid/'requests'/(seq+'.json'))==d
        old_rows=read(original/'analysis_001/session-metrics.json')
        extended=read(root/'analysis_001/summary.json');rows=read(root/'analysis_001/session-metrics.json')
        fresh=read(root/'baseline_analysis_001/summary.json')
        assert finished['model_summaries'][model]==sha(root/'analysis_001/summary.json')
        assert [r for r in rows if r['arm']!='basic_search']==old_rows
        assert extended['registered_sessions']==len(rows)==1600
        assert extended['method_count']==6 and extended['ablation_count']==2
        assert len(extended['comparisons']['primary'])==5 and len(extended['comparisons']['ablation'])==2
        values=extended['comparisons']['primary']
        assert [v['holm_p_upper'] for v in values]==holm([v['exact_cluster_sign_randomization_p_upper'] for v in values])
        original_summary=read(original/'analysis_001/summary.json')
        for arm in original_summary['by_arm']:
            assert extended['by_arm'][arm]==original_summary['by_arm'][arm]
        assert extended['comparisons']['ablation']==original_summary['comparisons']['ablation']
        for a,b in zip(values[:4],original_summary['comparisons']['primary']):
            assert {k:v for k,v in a.items() if k not in {'holm_p_upper','statistical_positive_identified'}}=={
                k:v for k,v in b.items() if k not in {'holm_p_upper','statistical_positive_identified'}}
        for row in rows:
            assert (row['score_lower'],row['score_upper'])==graded_validity(row)
            assert (row['cv_lower'],row['cv_upper'])==valid_at_threshold(row,1)
        for arm in extended['by_arm']:
            assert extended['by_arm'][arm]['n']==200 and extended['by_arm'][arm]['group_count']==24
            assert all(v['n']==50 for v in extended['by_type'][arm].values())
        generation=read(root/'generation-audit.json');scoring=root/'scoring_001';closed=read(scoring/'completion.json')
        assert generation['closed']==200 and generation['source_and_tool_replay_verified']
        assert generation['answers_jsonl_sha256']==sha(root/'answers.jsonl')
        assert closed['sessions']==200 and closed['execution_protocol_sha256']==sha(scoring/'protocol.json')
        for qid,d in generation['results_sha256'].items():
            assert sha(root/'generation/basic_search'/qid/'result.json')==d
        for key,d in closed['results_sha256'].items():
            assert sha(scoring/'sessions'/key/'result.json')==d
        bindings=read(root/'baseline_analysis_001/judge-request-bindings.json')
        for key,d in bindings.items():
            arm,qid,seq=key.split('/')
            record=scoring/'sessions'/arm/qid/'requests'/(seq+'.json')
            assert sha(record)==d
            receipt=read(record)
            assert receipt['endpoint']==approval['destination'] and receipt['model']=='qwen3-14b'
        assert len(bindings)==sum(fresh['judge']['request_statuses'].values())
        counts=Counter(e['name'] for qid in generation['results_sha256'] for e in read(root/'generation/basic_search'/qid/'result.json')['tool_events'])
        assert set(counts)<={'glob','grep','read_source'}
        models[model]=dict(sessions=1600,new_basic_search_sessions=200,original_rows_unchanged=True,
            basic_search_tools=dict(counts),judge_requests=len(bindings),summary_sha256=sha(root/'analysis_001/summary.json'))
    assets=M/'assets/chapter2/model_scales';manifest=read(assets/'source-manifest.json')
    assert manifest['sessions_each']==1600 and manifest['main_methods']==6
    for rel,d in manifest['input_sha256'].items():assert sha(W/rel)==d
    for name,d in manifest['outputs_sha256'].items():assert sha(assets/name)==d
    official=read(M/'official_manifest.json')
    assert sha(M/'main.pdf')==sha(M/'build/main.pdf')==official['pdf_sha256']
    assert official['review']['visual_review_status']=='passed'
    assert official['review']['full_session_count']==3200
    for rel,d in official['source_files_sha256'].items():assert sha(M/rel)==d
    plan=read(C/'publication-plan.json')
    assert plan['basic_search_extension']['status']=='complete'
    assert plan['basic_search_extension']['completed_new_sessions']==400
    assert 'basic_search' in plan['planned_methods']
    assert plan['answer_model_matrix']['qwen3-32b']['status']=='waiting_user_api'
    report=dict(passed=True,questions=200,main_methods=6,ablations=2,models=models,total_quality_sessions=3200,
        original_2800_unchanged=True,extended_main_family_size=5,ablation_family_size=2,
        explicit_export_approval_sha256=sha(R/'explicit-export-authorization.json'),
        official_pdf_sha256=official['pdf_sha256'],official_manifest_sha256=sha(M/'official_manifest.json'),
        official_pdf_pages=official['review']['pages'],verifier_source_sha256=sha(Path(__file__)))
    target=C/'basic-search-delivery-verification.json'
    target.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':main()
