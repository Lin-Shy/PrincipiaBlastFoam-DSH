"""代理完整评分的独立终态核验与原统计入口；禁止联网或读取凭据。"""
import argparse
from collections import Counter
from datetime import datetime,timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

from chapter2_local_full_review_gate import source_release_args
from chapter2_billing_resume_controller import exclusive_stage_lock
from chapter2_local_post_score_context import deny_network_and_credentials
from chapter2_proxy_costs import physical_proxy_cost


def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,v):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('x',encoding='utf-8') as f:json.dump(v,f,ensure_ascii=False,indent=2)


def validate_handoff(root,registration=Path('setup/proxy_bulk_resume_001/registration.json')):
    value=read(root/Path(registration).parent/'postprocess-handoff-001.json')
    if (value.get('schema')!='proxy_post_score_handoff_v1' or value.get('registered_scores')!=13536
            or value.get('source_reviews')!=1248 or value.get('comparison_families')!=[8,6,42,5]
            or value.get('model_requests')!=0 or value.get('actual_execution_complete') is not False):
        raise ValueError('Bound full proxy post-processing handoff required')
    for path,digest in value['inputs_sha256'].items():
        if sha(path)!=digest:raise ValueError('Post-processing implementation or input drift: '+path)
    return value


def native_gate(root,registration,witness):
    regpath=root/registration;reg=read(regpath)
    proof=read(witness)
    run=root/reg['run_folder'];complete=run/'completion.json'
    launch=read(root/reg.get('native_launch_evidence_relative_path',
        'audit/proxy_bulk_transition_001/progress-001.json'))['native_launch']
    if (proof.get('schema')!='proxy_bulk_root_native_observation_v1'
            or type(proof.get('native_returncode')) is not int or proof['native_returncode']!=0
            or proof.get('native_session_id')!=launch['session_id']
            or proof.get('registration_sha256')!=sha(regpath)
            or not isinstance(proof.get('native_terminal_tool_chunk'),str) or not proof['native_terminal_tool_chunk']
            or not complete.exists() or proof.get('completion_sha256')!=sha(complete)):
        raise ValueError('Actual root-observed proxy native exit zero and bound completion required')
    completion=read(complete)
    if (completion.get('schema')!='original_proxy_bulk_completion_v1'
            or completion.get('registration_sha256')!=sha(regpath)
            or completion.get('completed_scores')!=13536 or completion.get('planned_scores')!=13536
            or completion.get('full_scope_complete') is not True):
        raise ValueError('Full fixed proxy score scope required')
    return reg,completion


def original_context(root):
    proof=read(root/'audit/complete_source_release_verification_001.json')
    args=source_release_args(proof);package=root/'setup/full_review_grading_execution_003'
    sys.path.insert(0,str(package))
    from guard import validate_package
    manifest=validate_package(package,'controller')
    if sha(package/'manifest.json')!=proof['frozen_execution_package_manifest_sha256']:
        raise ValueError('Frozen full-review package drift')
    runtime=Path(manifest['bases']['grading']['runtime'])
    sys.path.insert(0,str(runtime/'src'));sys.path.insert(0,str(runtime/'experiments/retrieval_method'))
    from chapter2_knowledge_evaluation import verify_setup,verify_dataset
    from chapter2_knowledge_formal_plan import validate_activation
    setup=read(args.evaluation);plan=verify_setup(setup,args.plan)
    verify_dataset(args.dataset,setup['dataset_seal_sha256'])
    validate_activation(read(args.activation),plan,sha(args.plan))
    return SimpleNamespace(args=args,plan=plan,setup=setup,runtime=runtime,package=package)


def verify_terminal(root,regpath,witness,output):
    reg,completion=native_gate(root,regpath,witness)
    for name,digest in reg['implementation_sha256'].items():
        if sha(Path(__file__).parent/name)!=digest:raise ValueError('Registered proxy execution source drift')
    for name,digest in reg['evidence_sha256'].items():
        if sha(root/name)!=digest:raise ValueError('Registered proxy evidence drift')
    matrix=read(root/'setup/local_uniform_judge_001/matrix-preparation.json')
    for mapping in ['input_sha256','legacy_score_bindings_sha256']:
        for name,digest in matrix[mapping].items():
            if sha(root/name)!=digest:raise ValueError('Original input or score drift')
    for name,digest in read(root/reg['baseline_inventory'])['files_sha256'].items():
        if sha(root/name)!=digest:raise ValueError('Historic proxy file changed')
    ctx=original_context(root)
    from full_review import verify_complete_release
    reviews,reviewbindings,reviewrows,release=verify_complete_release(ctx.args,persist=False)
    if len(reviews)!=1248:raise ValueError('Full prospective source review required')
    from chapter2_knowledge_formal_plan import activation_identity,digest
    from chapter2_knowledge_evaluation import primary_bounds
    activation=read(ctx.args.activation);protocols={};scores=Counter();identities=set();requests=[]
    out=root/'formal_scores'
    for cell in ctx.plan['cells']:
        cid=cell['id'];path=out/cid/'protocol.json'
        expected=dict(schema='activated_knowledge_qa_formal_grading_cell_v1',formal_result=True,
            cell_id=cid,plan_sha256=sha(ctx.args.plan),activation_sha256=activation_identity(activation,sha(ctx.args.activation),cid),
            evaluation_sha256=sha(ctx.args.evaluation),endpoint=reg['endpoint'],judge_model='qwen3-14b',
            rubric_version='source_free_v7',transport_attempts_max=3,content_retries=0)
        if read(path)!=expected:raise ValueError('Proxy cell protocol differs')
        protocols[cid]=sha(path)
    planned={(r['cell_id'],r['question_id']) for r in matrix['generated_sessions']}
    if len(planned)!=13536:raise ValueError('Matrix is not the full fixed scope')
    for item in matrix['generated_sessions']:
        cid,qid=item['cell_id'],item['question_id'];key=(cid,qid)
        result=root/'formal_generation/cells'/cid/'sessions'/qid/'result.json'
        scorepath=out/cid/'sessions'/qid/'score.json';score=read(scorepath)
        binding=dict(question_id=qid,formal_cell_id=cid,formal_result=True,result_sha256=item['result_sha256'],
            generation_status=item['generation_status'],protocol_sha256=protocols[cid],
            reference_judgment_sha256=digest(reviewrows[key]) if key in reviewrows else None)
        if sha(result)!=item['result_sha256'] or any(score.get(k)!=v for k,v in binding.items()):
            raise ValueError('Score identity or preceding source judgment differs')
        if read(scorepath.parent/'score-binding.json')!=dict(score_sha256=sha(scorepath),result_sha256=sha(result),protocol_sha256=protocols[cid]):
            raise ValueError('Score byte binding differs')
        if score['status'] not in {'judged','partially_judged','judge_unknown','generation_failed'}:
            raise ValueError('Nonterminal score')
        primary_bounds(score);scores[score['status']]+=1;identities.add(key)
        requests.extend((scorepath.parent/'requests').glob('*.json'))
    if identities!=planned or dict(scores)!=completion['status_counts']:
        raise ValueError('Actual full score statuses differ from completion')
    actual={(p.parent.parent.parent.relative_to(out).as_posix(),p.parent.name) for p in out.glob('**/sessions/*/score.json')}
    if actual!=planned:raise ValueError('Unexpected or missing score identities')
    unresolved={}
    for path in requests:
        record=read(path)
        if record['status'] in {'in_flight','prepared'}:
            relative=path.relative_to(root).as_posix();unresolved[relative]=sha(path)
            score=read(path.parent.parent/'score.json')
            if (score.get('reason')!='previous_proxy_client_interrupted' or score['metrics']['complete_valid_answer'] is not None
                    or score.get('sealed_unresolved_requests_sha256',{}).get(relative)!=sha(path)
                    or score.get('requests_reissued') is not False):
                raise ValueError('Historic interruption does not have a bound unknown score')
    if unresolved!=reg['sealed_unresolved_requests_sha256']:
        raise ValueError('New unresolved requests or changed interruption seal')
    costs=physical_proxy_cost(requests,root,unresolved)
    files={p.relative_to(root).as_posix():sha(p) for p in out.rglob('*.json')}
    save(output,dict(schema='complete_proxy_score_native_terminal_v1',utc=datetime.now(timezone.utc).isoformat(),
        registration_sha256=sha(root/regpath),root_native_observation_sha256=sha(witness),native_returncode=0,
        verified_terminal_scores=13536,verified_independent_reviews=1248,verified_citation_reviews=1248,
        source_release_sha256=sha(root/'audit/complete_source_release_verification_001.json'),
        matrix_sha256=sha(root/'setup/local_uniform_judge_001/matrix-preparation.json'),
        completion_sha256=sha(root/reg['run_folder']/'completion.json'),score_status_counts=scores,
        preserved_proxy_files_sha256=files,physical_costs=costs,
        sealed_upstream_unknown_requests=unresolved,new_unresolved_requests=0,
        cost_adapter_sha256=sha(Path(__file__).with_name('chapter2_proxy_costs.py')),
        cost_collector_sha256=sha(Path(__file__).with_name('chapter2_knowledge_stage_costs.py')),
        local_scores_used=False,implementation_sha256=sha(Path(__file__)),full_goal_complete=False))
    print(json.dumps(dict(verified_scores=13536,source_reviews=1248,physical_attempts=costs['physical_attempts'])),flush=True)


def validate_terminal(root,terminal,regpath):
    value=read(terminal)
    if (value.get('schema')!='complete_proxy_score_native_terminal_v1'
            or value.get('native_returncode')!=0 or value.get('verified_terminal_scores')!=13536
            or value.get('verified_independent_reviews')!=1248 or value.get('verified_citation_reviews')!=1248
            or value.get('local_scores_used') is not False or value.get('new_unresolved_requests')!=0
            or value.get('registration_sha256')!=sha(root/regpath)
            or value.get('cost_adapter_sha256')!=sha(Path(__file__).with_name('chapter2_proxy_costs.py'))
            or value.get('cost_collector_sha256')!=sha(Path(__file__).with_name('chapter2_knowledge_stage_costs.py'))
            or value.get('implementation_sha256')!=sha(Path(__file__))):
        raise ValueError('Independent complete proxy score verification required')
    if not value.get('preserved_proxy_files_sha256'):raise ValueError('Full score file bindings absent')
    for name,digest in value['preserved_proxy_files_sha256'].items():
        if sha(root/name)!=digest:raise ValueError('Verified proxy file changed')
    return value


def analysis_command(root,output):
    old=read(root/'audit/full_matrix_analysis_handoff_preparation_001.json')
    command=list(old['frozen_analyzer_command'])
    command[0]=sys.executable
    command[command.index('--output')+1]=str(output)
    command[command.index('--scores')+1]=str(root/'formal_scores')
    command[command.index('--results')+1]=str(root/'formal_generation/cells')
    return command


def run_analysis_worker(root,registration,terminal):
    validate_terminal(root,terminal,registration)
    ctx=original_context(root)
    import chapter2_analyze_knowledge_formal as analyzer
    old=read(root/'audit/full_matrix_analysis_handoff_preparation_001.json')
    original=Path(old['frozen_analyzer_command'][1])
    if Path(analyzer.__file__).resolve()!=original.resolve() or sha(original)!=old['frozen_inputs_sha256'][str(original)]:
        raise ValueError('Original frozen statistics implementation differs')
    reg=read(root/registration)
    # Only physical ledger normalization changes. All answer metrics, group
    # weighting, bounds, bootstrap/sign-flip tests and Holm families are original.
    analyzer.physical_cost=lambda paths:physical_proxy_cost(paths,root,reg['sealed_unresolved_requests_sha256'])
    command=analysis_command(root,root/'formal_analysis/two_model_proxy_001')
    sys.argv=command[1:];analyzer.main()


def run_analysis(root,registration,terminal):
    validate_terminal(root,terminal,registration)
    output=root/'formal_analysis/two_model_proxy_001';launch=root/'audit/proxy_full_analysis_launch_001'
    if output.exists() or launch.exists():raise FileExistsError('Preserve partial or completed analysis before diagnosis')
    launch.mkdir()
    command=[sys.executable,str(Path(__file__).absolute()),'--activity',str(root),'--registration',str(registration),
        '--native-terminal',str(terminal),'--kind','analysis-worker']
    save(launch/'start.json',dict(command=command,terminal_sha256=sha(terminal),implementation_sha256=sha(Path(__file__))))
    env=dict(os.environ,PYTHONIOENCODING='utf-8',PYTHONPATH='',HF_HUB_OFFLINE='1')
    with (launch/'execution.txt').open('x',encoding='utf-8') as log:
        result=subprocess.run(command,env=env,stdout=log,stderr=subprocess.STDOUT)
    save(launch/'process-terminal.json',dict(native_returncode=result.returncode))
    if result.returncode!=0:raise RuntimeError('Proxy analysis failed; inspect saved log before further action')
    report=read(output/'report.json')
    if (report.get('planned_sessions')!=13536 or report.get('generation_results')!=13536
            or report.get('completed_independent_reviews')!=1248 or len(report.get('series',{}))!=50
            or report.get('human_truth') is not False or not report['completion_gate']['whole_registered_scope_complete']):
        raise ValueError('Analysis full scope differs')
    for section in ['fixed_comparisons','reviewed_comparisons']:
        c=report[section]
        if [len(c[k]) for k in ['primary','mechanism','supplements','model_size']]!=[8,6,42,5]:
            raise ValueError('Original statistical comparison families differ')
        if any(r['significance_claim_allowed'] for k in ['supplements','model_size'] for r in c[k].values()):
            raise ValueError('Supplementary comparisons remain descriptive')
    files={n:sha(output/n) for n in ['report.json','observations.json','prospective_trajectories.json']}
    save(launch/'terminal.json',dict(schema='complete_proxy_analysis_terminal_v1',native_returncode=0,
        terminal_score_proof_sha256=sha(terminal),outputs_sha256=files,registered_scores=13536,source_reviews=1248,
        analysis_series=50,comparison_families=[8,6,42,5],physical_cost_adapter_sha256=sha(Path(__file__).with_name('chapter2_proxy_costs.py')),
        frozen_statistics_changed=False,model_calls=0,full_goal_complete=False))
    print('Full proxy analysis complete; interpretation and publication remain.',flush=True)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--activity',type=Path,required=True)
    p.add_argument('--registration',type=Path,default=Path('setup/proxy_bulk_resume_001/registration.json'))
    p.add_argument('--native-observation',type=Path)
    p.add_argument('--native-terminal',type=Path)
    p.add_argument('--output',type=Path)
    p.add_argument('--kind',choices=['verify','analysis','analysis-worker'],required=True)
    a=p.parse_args();root=a.activity.absolute();deny_network_and_credentials();validate_handoff(root,a.registration)
    terminal=a.native_terminal or root/'audit/proxy_bulk_transition_001/full-score-native-terminal-001.json'
    if a.kind=='verify':
        if a.native_observation is None:raise ValueError('Actual root native observation required')
        with exclusive_stage_lock(root/'formal_scores/billing-resume-controller.lock'):
            verify_terminal(root,a.registration,a.native_observation,a.output or terminal)
    elif a.kind=='analysis':run_analysis(root,a.registration,terminal)
    else:run_analysis_worker(root,a.registration,terminal)


if __name__=='__main__':main()
