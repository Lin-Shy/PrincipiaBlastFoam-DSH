"""代理全量统计后的辅助维度、轨迹、全阶段成本与出版交接。"""
import argparse
from pathlib import Path
import subprocess
from types import SimpleNamespace

from chapter2_proxy_postprocess import read,sha,save,validate_handoff,validate_terminal,original_context
from chapter2_local_post_score_context import deny_network_and_credentials,load_helper
from chapter2_build_local_post_reports import auxiliary,trajectories,csv_file
from chapter2_knowledge_stage_costs import reconcile


def analysis_context(root,registration,terminal):
    scoreproof=validate_terminal(root,terminal,registration)
    launch=root/'audit/proxy_full_analysis_launch_001';native=read(launch/'terminal.json')
    analysis=root/'formal_analysis/two_model_proxy_001';report=read(analysis/'report.json')
    if (native.get('schema')!='complete_proxy_analysis_terminal_v1' or native.get('native_returncode')!=0
            or native.get('terminal_score_proof_sha256')!=sha(terminal)
            or native.get('registered_scores')!=13536 or native.get('source_reviews')!=1248
            or native.get('analysis_series')!=50 or native.get('comparison_families')!=[8,6,42,5]
            or native.get('frozen_statistics_changed') is not False or native.get('model_calls')!=0):
        raise ValueError('Complete original proxy analysis native receipt required')
    for name,digest in native['outputs_sha256'].items():
        if sha(analysis/name)!=digest:raise ValueError('Completed analysis output changed')
    if (report.get('human_truth') is not False or report.get('planned_sessions')!=13536
            or report.get('completed_independent_reviews')!=1248 or len(report.get('series',{}))!=50
            or report.get('prospective_trajectory_records')!=1248
            or not report.get('completion_gate',{}).get('whole_registered_scope_complete')):
        raise ValueError('Whole proxy analysis cohort required')
    for path,digest in report['input_file_bindings'].items():
        if sha(path)!=digest:raise ValueError('Analysis input changed')
    ctx=original_context(root)
    if ctx.args.results.resolve()!=(root/'formal_generation/cells').resolve():
        raise ValueError('Original generation directory identity differs')
    ctx.args.results=root/'formal_generation/cells'
    from chapter2_analyze_knowledge_formal import series_specs
    from chapter2_knowledge_evaluation import evidence_coverage
    from chapter2_qa_statistics import aggregate_planned
    return SimpleNamespace(root=root,args=ctx.args,plan=ctx.plan,setup=ctx.setup,scoreproof=scoreproof,
        analysis=analysis,report=report,report_path=analysis/'report.json',native_path=launch/'terminal.json',
        observations=read(analysis/'observations.json'),trajectories=read(analysis/'prospective_trajectories.json'),
        cells={c['id']:c for c in ctx.plan['cells']},specs=series_specs(ctx.plan),aggregate=aggregate_planned,
        annotations={q['id']:q for q in read(ctx.args.dataset/'scoring/annotations.json')},
        evidence=read(ctx.args.dataset/'scoring/evidence.json'),evidence_coverage=evidence_coverage)


def descriptive(root,registration,terminal,kind):
    ctx=analysis_context(root,registration,terminal)
    output=root/'formal_analysis'/('auxiliary_dimensions_proxy_001' if kind=='auxiliary' else 'prospective_request_inclusion_proxy_001')
    if output.exists():raise FileExistsError('Preserve existing descriptive output before diagnosis')
    helpername='auxiliary_dimension_aggregation_001.py' if kind=='auxiliary' else 'trajectory_request_inclusion_001.py'
    prepname='auxiliary_report_preparation_001.json' if kind=='auxiliary' else 'trajectory_request_report_preparation_001.json'
    helperpath=root/'audit'/helpername;expected=read(root/'audit'/prepname)['prepared_scripts_sha256'][helpername]
    helper=load_helper(helperpath,expected)
    common=dict(formal_result=True,judge_deployment='qwen_proxy',human_truth=False,model_requests=0,
        native_score_terminal_sha256=sha(terminal),native_analysis_terminal_sha256=sha(ctx.native_path),
        full_analysis_report_sha256=sha(ctx.report_path),implementation_sha256=sha(Path(__file__)),
        helper_sha256=sha(helperpath),significance_claim_allowed=False,new_inferential_families=0,full_goal_complete=False)
    if kind=='auxiliary':
        summary,table,failures,bindings=auxiliary(ctx,helper,score_root=root/'formal_scores');output.mkdir()
        csv_file(output/'auxiliary_dimensions.csv',['series','stratum','dimension','planned_questions','planned_observations','groups',
            'group_macro_lower','group_macro_upper','unavailable','semantic_unknown','not_applicable_excluded','raw_pass','raw_fail'],table)
        csv_file(output/'raw_failure_categories.csv',['series','raw_category','planned_observations','flagged','raw_label_not_flagged','unassessed_or_not_applicable'],failures)
        value=dict(common,schema='complete_fixed_v7_descriptive_auxiliary_report_v1',planned_sessions=13536,series_count=50,
            series=summary,raw_score_file_bindings=bindings,dimension_csv_sha256=sha(output/'auxiliary_dimensions.csv'),
            raw_failure_csv_sha256=sha(output/'raw_failure_categories.csv'),primary_scores_and_source_opinions_unchanged=True,
            limitations=['Automated auxiliary labels have known errors; descriptive aggregation is not semantic validation or human truth.',
                'Unavailable/unknown dimensions retain planned bounds; applicability excludes only sealed nonconditional questions.',
                'Raw failure categories overlap; counts are not causal explanations.'])
    else:
        rows,table,bindings,flags=trajectories(ctx,helper);output.mkdir()
        csv_file(output/'prospective_request_inclusion.csv',['cell','question','model','kind','method','repeat','generation_status',
            'model_turns','tool_attempts','tool_errors','ordinary_tool_characters','tool_or_prepared_ledger_lines','client_request_included_lines',
            'ledger_lines_not_in_request','original_complete_evidence','client_payload_complete_evidence','privileged_prepared_lines',
            'privileged_request_lines','privileged_input_characters','reference_count'],table)
        value=dict(common,schema='full_prospective_recorded_request_original_inclusion_report_v1',prospective_cases=1248,questions=16,
            all_cases_retained_including_failures=True,records=rows,descriptive_flag_counts=flags,result_bindings=bindings,
            csv_sha256=sha(output/'prospective_request_inclusion.csv'),selection_sha256=sha(ctx.args.review_selection),
            original_frozen_coverage_and_primary_scores_changed=False,provider_processing_or_semantic_reading_attested=False,
            limits='Tool delivery and client request inclusion are distinct; neither attests provider processing or semantic reading. All fixed cases and failures remain.')
    for name,digest in bindings.items():
        if sha(root/name)!=digest:raise ValueError('Descriptive input changed')
    save(output/'report.json',value);print('Complete proxy '+kind+' report created; descriptive only.',flush=True)


def costs(root,registration,terminal):
    ctx=analysis_context(root,registration,terminal);output=root/'audit/stage_costs_proxy_final_001'
    if output.exists():raise FileExistsError('Preserve existing cost report before diagnosis')
    # Local scoring was intentionally drained; verify that snapshot before
    # including its separate failed/partial measurement costs.
    localnative=read(root/'audit/proxy_bulk_transition_001/local-drain-native-001.json')
    inventory=root/'audit/proxy_bulk_transition_001/local-drained-inventory-001.json'
    if localnative['local_inventory_sha256']!=sha(inventory) or localnative['upstream_unresolved_requests']!=0:
        raise ValueError('Independent local drain receipt required')
    for name,digest in read(inventory)['files_sha256'].items():
        if sha(root/name)!=digest:raise ValueError('Separate local scoring artifact changed')
    report=reconcile(root);original=read(root/'audit/two_model_closed_generation_costs_001.json')['total_generation_only']
    proxy=ctx.scoreproof['physical_costs'];stage=report['stages']['formal_primary_grading']
    for key in ['physical_attempts','usage_known_attempts','usage_unknown_attempts','known_prompt_tokens','known_completion_tokens','known_total_tokens']:
        if report['stages']['formal_generation'][key]!=original[key]:raise ValueError('Original generation costs changed')
        if stage[key]!=proxy[key]:raise ValueError('Full proxy grading cost differs from independent terminal ledger')
        if report['grand_total'][key]!=sum(s[key] for s in report['stages'].values()):raise ValueError('Stage totals do not reconcile')
    if report['money_cost'] is not None or report['local_compute_cost'] is not None:
        raise ValueError('Unmetered costs remain unknown')
    report.update(collector_sha256=sha(Path(__file__).with_name('chapter2_knowledge_stage_costs.py')),
        native_score_terminal_sha256=sha(terminal),local_drain_receipt_sha256=sha(root/'audit/proxy_bulk_transition_001/local-drain-native-001.json'),
        final_proxy_scoring_process_closed=True,local_and_proxy_measurements_separate=True)
    output.mkdir();save(output/'report.json',report)
    save(output/'terminal.json',dict(schema='complete_proxy_activity_cost_terminal_v1',report_sha256=sha(output/'report.json'),
        native_score_terminal_sha256=sha(terminal),original_generation_costs_preserved=True,
        proxy_costs_match_independent_terminal=True,local_costs_included_separately=True,
        historical_upstream_unknowns_retained=True,model_calls=0,full_goal_complete=False))
    print('All-stage proxy/local costs reconciled; unknown usage and money retained.',flush=True)


def export(root,registration,terminal):
    ctx=analysis_context(root,registration,terminal)
    supplements=[]
    for directory,names in [('auxiliary_dimensions_proxy_001',['auxiliary_dimensions.csv','raw_failure_categories.csv']),
            ('prospective_request_inclusion_proxy_001',['prospective_request_inclusion.csv'])]:
        folder=root/'formal_analysis'/directory;report=read(folder/'report.json')
        if (report.get('judge_deployment')!='qwen_proxy' or report.get('native_score_terminal_sha256')!=sha(terminal)
                or report.get('full_analysis_report_sha256')!=sha(ctx.report_path) or report.get('model_requests')!=0
                or report.get('implementation_sha256')!=sha(Path(__file__))
                or report.get('human_truth') is not False or report.get('significance_claim_allowed') is not False):
            raise ValueError('Bound full descriptive report required')
        expected_hashes=({'auxiliary_dimensions.csv':report.get('dimension_csv_sha256'),
                         'raw_failure_categories.csv':report.get('raw_failure_csv_sha256')}
                        if len(names)==2 else {'prospective_request_inclusion.csv':report.get('csv_sha256')})
        if len(names)==2:
            if report.get('planned_sessions')!=13536 or len(report.get('series',{}))!=50:
                raise ValueError('All auxiliary series required')
        elif (report.get('prospective_cases')!=1248 or len(report.get('records',[]))!=1248
                or report.get('all_cases_retained_including_failures') is not True):
            raise ValueError('All fixed trajectories including failures required')
        for name in names:
            if sha(folder/name)!=expected_hashes[name]:raise ValueError('Descriptive table changed')
            supplements.append(folder/name)
    costdir=root/'audit/stage_costs_proxy_final_001';cost=read(costdir/'terminal.json')
    if (cost.get('report_sha256')!=sha(costdir/'report.json') or cost.get('native_score_terminal_sha256')!=sha(terminal)
            or cost.get('proxy_costs_match_independent_terminal') is not True
            or cost.get('original_generation_costs_preserved') is not True
            or cost.get('local_costs_included_separately') is not True):
        raise ValueError('Complete all-stage costs required')
    prep=read(root/'audit/final_publication_export_preparation_002.json');command=list(prep['command'])
    if sha(command[1])!=prep['unchanged_exporter_sha256']:raise ValueError('Canonical exporter changed')
    command[command.index('--analysis')+1]=str(ctx.analysis)
    output=Path(command[command.index('--output')+1]);launch=root/'audit/proxy_publication_export_001'
    if output.exists() or launch.exists():raise FileExistsError('Preserve publication directory before diagnosis')
    launch.mkdir();save(launch/'start.json',dict(command=command,score_terminal_sha256=sha(terminal),analysis_sha256=sha(ctx.report_path)))
    with (launch/'execution.txt').open('x',encoding='utf-8') as log:
        result=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT)
    save(launch/'process-terminal.json',dict(native_returncode=result.returncode))
    if result.returncode!=0:raise RuntimeError('Publication failed; inspect existing log/output')
    manifest=read(output/'source-manifest.json')
    expected_outputs={name+'.'+ext for name in prep['figures'] for ext in ['pdf','svg','png']}|{
        'citation_cohort.csv','all_series.csv','question_type_strata.csv','cell_costs.csv','failure_counts.csv','paired_comparisons.csv'}
    if (manifest.get('script_sha256')!=prep['unchanged_exporter_sha256']
            or manifest.get('font_sha256')!=prep['font_sha256']
            or set(manifest.get('outputs_sha256',{}))!=expected_outputs
            or manifest.get('formal_result') is not True or manifest.get('model_requests')!=0):
        raise ValueError('Complete original exporter inventory required')
    for name,digest in manifest['outputs_sha256'].items():
        if sha(output/name)!=digest:raise ValueError('Publication file changed')
    for path in supplements:
        target=output/path.name
        with target.open('xb') as stream:stream.write(path.read_bytes())
    expected=set(prep['figures']);actual={p.stem for p in output.glob('*.pdf')}
    if actual!=expected or len(list(output.glob('*.csv')))!=9:
        raise ValueError('Exactly seven publication figures and nine tables required')
    save(launch/'terminal.json',dict(schema='complete_proxy_publication_export_v1',native_returncode=0,
        publication_directory=str(output),outputs_sha256={p.name:sha(p) for p in output.iterdir() if p.is_file()},
        figures=7,csv_tables=9,model_calls=0,personal_plot_review_pending=True,final_thesis_defense_sync_pending=True,
        full_goal_complete=False))
    print('Seven figures and nine tables exported; personal review and thesis/defense synchronization remain.',flush=True)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--activity',type=Path,required=True)
    p.add_argument('--registration',type=Path,default=Path('setup/proxy_bulk_resume_001/registration.json'))
    p.add_argument('--native-terminal',type=Path)
    p.add_argument('--kind',choices=['auxiliary','trajectory','costs','export'],required=True)
    a=p.parse_args();root=a.activity.absolute();deny_network_and_credentials();validate_handoff(root,a.registration)
    terminal=a.native_terminal or root/'audit/proxy_bulk_transition_001/full-score-native-terminal-001.json'
    if a.kind in {'auxiliary','trajectory'}:descriptive(root,a.registration,terminal,a.kind)
    elif a.kind=='costs':costs(root,a.registration,terminal)
    else:export(root,a.registration,terminal)


if __name__=='__main__':main()
