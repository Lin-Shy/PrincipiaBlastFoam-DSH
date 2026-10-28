"""Dev40 generation, frozen dual-judge scoring and full-denominator comparison.

Post-audit operational authorization does not rewrite the failed original audit.
"""
import argparse
from collections import defaultdict
import hashlib
import json
import os
from pathlib import Path
import statistics
import sys

from central_execution import DEFAULT_RUN, PROJECT, read, save, sha, now, Registry

ROOT=DEFAULT_RUN/'experiments/agentic/dev40'
METHODS=['graph','bm25','e5','bge_m3','bm25_e5','bm25_bge_m3','bm25_parent','basic','direct','no_cross','no_aliases','no_traversal','anchor_only']
GRAPH={'graph','no_cross','no_aliases','no_traversal','anchor_only'}
SPLIT=DEFAULT_RUN/'data'
QUESTIONS=SPLIT/'dev40/model/questions.json'


def prepare():
    qs=read(QUESTIONS)
    assert len(qs)==40 and len({q['id'] for q in qs})==40 and all(set(q)=={'id','question'} for q in qs)
    assert len(METHODS)==13
    configs=[];tasks=[]
    registry=Registry()
    for model in ['qwen3_8b','qwen3_14b']:
        route=registry.resolve(model)
        for method in METHODS:
            for cap in ([None] if method=='direct' else [2000,4000,6000]):
                key=model+'__'+method+'__'+('no_tools' if cap is None else str(cap))
                cfg=dict(config_id=key,model_key=model,logical_model=registry.models[model]['logical_id'],method_id=method,
                    candidate_parameters={} if cap is None else dict(tool_calls=8,one_characters=cap,total_characters=cap*4),
                    combined_context_tokens=32768,input_token_cap=30720,output_token_cap=2048,
                    top_slots=10 if method not in ('basic','direct') else None,
                    method_tools='none' if method=='direct' else 'glob/grep/read' if method=='basic' else 'dedicated_backend/read',
                    endpoint=route['endpoint'],api_model_id=route['api_model_id'],
                    concurrency_cap=8 if model=='qwen3_8b' else 20,temperature=0,
                    generation_implementation='AutonomousKnowledgeAgent with exact Dev40 questions; preserve dedicated/basic/direct tool permissions',
                    source='new candidate; not an alias for historical answers')
                configs.append(cfg)
                for q in qs:
                    tasks.append(dict(task_id=key+'__'+q['id'],config_id=key,model_key=model,method_id=method,question_id=q['id'],
                        output_directory='generation/'+key+'/'+q['id']))
    resources=DEFAULT_RUN/'data/resources'
    provenance=resources
    bindings=[QUESTIONS,SPLIT/'split_freeze.json',resources/'source-map.json',resources/'corpus-manifest.json',
        resources/'graphs/selected.json',
        provenance/'indexes/bge_dense_v1/manifest.json']
    save(ROOT/'candidate_matrix.json',dict(created_utc=now(),methods=METHODS,models=['qwen3_8b','qwen3_14b'],
        configurations=configs,configuration_count=len(configs),questions=40,tasks=len(tasks),
        optimization_scope='Shared delivery character cap only. Backend algorithm parameters stay fixed in this first grid; expand only with an explicit new preregistered grid.',
        fixed_parameters='32K combined, temperature 0, 8 tool calls, 10 candidate slots; direct has one no-tools candidate',
        model_output_budget='2048 per request, 16384 total; final reserve 2048; same budgets as initial Dev120',
        selection=dict(metrics=['EAS_arith','EAS_geo'],metric='Report both separately over all 40 Dev questions; compare each independently',
            unknown='Report upper/lower bounds and unknown count; no imputed labels',
            failure='generation failures contribute zero in the full 40-question denominator',
            ties=['less total delivered characters','lexicographic configuration ID'],
            required_coverage='All 13 methods x 2 models; each candidate has all 40 results and both judge observations',
            no_test_data=True),
        bindings={str(p.relative_to(PROJECT.parent)):sha(p) for p in bindings},
        registry_sha256=registry.hashes,design_sha256=sha(PROJECT.parent/'graduation-thesis-materials/graduation-research/chapters/chapter02.md'),
        generated_sessions=0,api_calls=0,historical_results_reused=False,
        online_generation_ready=False,gate_reasons=['Dual-judge calibration not accepted','Question-ID audit not completed','Method parameter selection not frozen'],
        runnable_now=['offline-check one dedicated backend','select fully observed candidate CSV/JSON after later judging'],
        remaining_engineering=['Bind generation executor for all 13 tool permissions to this candidate matrix','Online 8B/14B identity/usage preflight after evaluation acceptance']))
    file=ROOT/'session_tasks.jsonl'
    with file.open('x',encoding='utf-8') as f:
        for task in tasks:f.write(json.dumps(task,ensure_ascii=False)+'\n')
    save(ROOT/'integrity.json',dict(matrix_sha256=sha(ROOT/'candidate_matrix.json'),tasks_sha256=sha(file),
        exact_question_ids=[q['id'] for q in qs],baseline_sessions=13*2*40,planned_candidate_sessions=len(tasks),
        source_sha256=sha(Path(__file__)),gold_read=False,test_questions_read=False,audit_labels_read=False))
    print(json.dumps(dict(configurations=len(configs),tasks=len(tasks),baseline_sessions=1040,api_calls=0)))


def offline_check(method):
    if method not in METHODS:raise ValueError('Unregistered method')
    folder=ROOT/'offline_checks'/method
    if folder.exists():raise FileExistsError('Never overwrite a retrieval check')
    os.environ['HF_HUB_OFFLINE']='1';os.environ['TRANSFORMERS_OFFLINE']='1'
    sys.path[:0]=[str(PROJECT/'experiments/chapter2_round2'),str(PROJECT/'experiments/retrieval_method'),str(PROJECT/'src')]
    import common
    common.ARCHIVE=DEFAULT_RUN/'data/resources';common.RESOURCES=DEFAULT_RUN/'data/resources';common.QUESTIONS=QUESTIONS
    from chapter2_knowledge_input_guard import install
    install(QUESTIONS)
    opened=[]
    def hook(event,args):
        if event in ('socket.connect','socket.connect_ex','socket.getaddrinfo'):raise PermissionError('Offline retrieval must not use network')
        if event=='open' and args and isinstance(args[0],(str,bytes,os.PathLike)):opened.append(str(args[0]))
    sys.addaudithook(hook)
    qs=read(QUESTIONS);q=qs[0]
    from principia_core.retrieval.knowledge_qa import FrozenKnowledgeCorpus,KnowledgeToolSession,KnowledgeBudget,tool_specs
    if method in ('basic','direct'):
        if method=='direct':
            tools=KnowledgeToolSession('none');specs=tool_specs(tools.method)
        else:
            from chapter2_basic_search_tools import BasicSearchSession,basic_specs
            corpus=FrozenKnowledgeCorpus(common.RESOURCES/'corpus',common.RESOURCES/'corpus-manifest.json')
            tools=BasicSearchSession(corpus,KnowledgeBudget());specs=basic_specs()
        assert len(specs)==0 if method=='direct' else {s['name'] for s in specs}=={'glob','grep','read_source'}
        save(folder/'result.json',dict(method=method,tools=specs,api_calls=0,status='offline_tool_permissions_verified'))
        return
    from retrieval import GraphEngine,TextEngine,SlotsBackend
    corpus=FrozenKnowledgeCorpus(common.RESOURCES/'corpus',common.RESOURCES/'corpus-manifest.json')
    engine=GraphEngine(method) if method in GRAPH else TextEngine(method)
    slots,trace=engine.query(q['question']);assert slots,'Empty retrieval result'
    deliveries=[]
    for cap in (2000,4000,6000):
        tools=KnowledgeToolSession('bm25',corpus,SlotsBackend(slots),KnowledgeBudget(8,cap,4*cap))
        response=tools.execute('search',{'query':q['question']})
        assert len(response)<=cap and tools.events[0]['status']=='returned'
        deliveries.append(dict(cap=cap,response=response,delivered_lines=tools.events[0]['delivered_original_lines']))
    graph_reads=[p for p in opened if Path(p).name in ('selected.json','no_cross.json','no_aliases.json')]
    if method not in GRAPH:assert not graph_reads,'Text backend read graph'
    save(folder/'result.json',dict(method=method,question_id=q['id'],slots=len(slots),status='offline_retrieval_verified',
        deliveries=deliveries,trace=trace,opened_files=sorted(set(opened)),graph_reads=graph_reads,scoring_reads=[],api_calls=0))
    print(json.dumps(dict(method=method,status='offline_retrieval_verified',slots=len(slots),api_calls=0)))


def shortlist():
    """One common-budget first stage; defer budget variants without running them."""
    matrix_path=ROOT/'candidate_matrix.json';matrix=read(matrix_path)
    active=[c for c in matrix['configurations'] if c['method_id']=='direct' or c['candidate_parameters']['one_characters']==6000]
    pairs={(c['model_key'],c['method_id']) for c in active}
    expected={(m,k) for m in ['qwen3_8b','qwen3_14b'] for k in METHODS}
    if pairs!=expected or len(active)!=26:raise ValueError('First stage must retain all 13 methods x 2 models')
    file=ROOT/'shortlist.json'
    if file.exists():
        old=read(file)
        if old['matrix_sha256']!=sha(matrix_path):raise ValueError('Shortlist matrix binding changed')
        return old
    ids=[c['config_id'] for c in active]
    result=dict(created_utc=now(),stage='common_6000_baseline',matrix_sha256=sha(matrix_path),
        active_configuration_ids=ids,active_configurations=len(active),
        deferred_configuration_ids=[c['config_id'] for c in matrix['configurations'] if c['config_id'] not in ids],
        deferred_configurations=len(matrix['configurations'])-len(active),expected_questions_per_candidate=40,
        baseline_sessions=26*40,full_grid_sessions=matrix['tasks'],
        rationale='Common 6000/24000 character budget matches initial Dev120; retain every method and both models before choosing budget refinements.',
        historical_answers='Preserve initial Dev120. Reuse only after generator, question, budgets, backend/implementation and protocol identities are verified; do not convert legacy scores.',
        expansion='Use Dev-only evidence from both EAS metrics and delivered-character costs to select budget refinements; do not schedule all 48 variants by default.',
        generation_started=False,api_calls=0,audit_acceptance_required=True,test_access=False)
    save(file,result)
    return result


def select(results,out,model=None):
    """Report separate rankings for both metrics; never authorize Test execution."""
    from scoring_review import guard_audit
    protocol=guard_audit()
    operational=False
    if protocol.get('status')!='final_frozen' or protocol.get('reliability_accepted') is not True:
        from dev40_scoring import guard_operational
        try:authority=guard_operational()
        except (PermissionError,FileNotFoundError,KeyError) as exc:
            raise PermissionError('Independent judge audit has not passed and no later operational authorization exists') from exc
        if not authority.get('dev40_parameter_selection_authorized'):raise PermissionError('Dev selection not authorized')
        operational=True
    from judge_contract import VERSION
    matrix=read(ROOT/'candidate_matrix.json');qs={q['id'] for q in read(QUESTIONS)}
    from dev40_runner import effective_configurations
    configs={c['config_id']:c for c in effective_configurations(matrix['configurations'],ROOT)};groups={n:defaultdict(dict) for n in ('arith','geo')}
    shortlist_path=ROOT/'shortlist.json'
    if shortlist_path.exists():
        current=read(shortlist_path)
        if current['matrix_sha256']!=sha(ROOT/'candidate_matrix.json'):raise ValueError('Shortlist matrix binding changed')
        configs={k:v for k,v in configs.items() if k in current['active_configuration_ids']}
    if model:configs={k:v for k,v in configs.items() if v['model_key']==model}
    seen=set();selected_rows=[]
    for r in read(results):
        if r.get('schema_version')!=VERSION:raise ValueError('Legacy/unspecified EAS cannot enter current Dev selection')
        key=r['config_id'];qid=r['question_id']
        if model and key in {c['config_id'] for c in matrix['configurations'] if c['model_key']!=model}:continue
        if key not in configs or qid not in qs or (key,qid) in seen:raise ValueError('Unknown config/question or duplicate')
        seen.add((key,qid))
        if not isinstance(r.get('generation_failed'),bool):raise ValueError('Missing generation status')
        if r.get('generation_present') is False or r.get('judges_complete') is False:
            raise ValueError('Actual generation and two independent judge observations required')
        selected_rows.append(r)
        for n in groups:
            if r['generation_failed']:bounds=[0.,0.]
            else:
                both=r.get('judge_eas_'+n+'_bounds',{})
                if set(both)!={'gpt_sol','deepseek_flash'}:raise ValueError('Both judges required for both metrics')
                for v in both.values():
                    if len(v)!=2 or any(type(x) not in (int,float) or not 0<=x<=100 for x in v) or v[0]>v[1]:raise ValueError('Invalid bounds')
                bounds=[statistics.mean(v[i] for v in both.values()) for i in (0,1)]
            groups[n][key][qid]=bounds
    output={}
    for n,grid in groups.items():
        if set(grid)!=set(configs) or any(set(g)!=qs for g in grid.values()):raise ValueError('Incomplete grid/full-40 denominator')
        aggregate={k:[sum(v[i] for v in g.values())/40 for i in (0,1)] for k,g in grid.items()}
        rankings={}
        for model_key in ([model] if model else ['qwen3_8b','qwen3_14b']):
            for method in METHODS:
                candidates=[k for k,c in configs.items() if c['model_key']==model_key and c['method_id']==method]
                rankings[model_key+'__'+method]=sorted(candidates,key=lambda k:(-aggregate[k][0],configs[k]['candidate_parameters'].get('total_characters',0),k))
        output['EAS_'+n]=dict(rankings=rankings,all_mean_bounds=aggregate)
    snapshot=Path(out).with_name('selection_input_'+(model or 'both_models')+'.json')
    if snapshot.exists():
        if read(snapshot)!=selected_rows:raise ValueError('Frozen model-specific selection input changed')
    else:save(snapshot,selected_rows)
    winners={key:{metric:value['rankings'][key][0] for metric,value in output.items()} for key in output['EAS_arith']['rankings']}
    consensus={key:dict(configs[next(iter(v.values()))],
                EAS_arith_mean_bounds=output['EAS_arith']['all_mean_bounds'][v['EAS_arith']],
                EAS_geo_mean_bounds=output['EAS_geo']['all_mean_bounds'][v['EAS_geo']])
        if len(set(v.values()))==1 else None for key,v in winners.items()}
    save(out,dict(schema_version=VERSION,status='dev_only_dual_metric_rankings_not_Test_authorization',metrics=output,
        metric_winners=winners,consensus_configurations=consensus,configurations_frozen=all(v is not None for v in consensus.values()),
        results_sha256=sha(snapshot),results_file=snapshot.name,original_full_grid_sha256=sha(results),matrix_sha256=sha(ROOT/'candidate_matrix.json'),
        shortlist_sha256=sha(shortlist_path) if shortlist_path.exists() else None,
        endpoint_migration_sha256=sha(ROOT/'endpoint_migration.json') if (ROOT/'endpoint_migration.json').exists() else None,
        infrastructure_recovery_sha256=sha(ROOT/'infrastructure_recovery.json') if (ROOT/'infrastructure_recovery.json').exists() else None,
        judge_freeze_id=protocol.get('freeze',{}).get('freeze_id'),
        denominator=40,unknown_bounds_retained=True,test_access=False,original_audit_passed=not operational,
        post_audit_operational_authorization_used=operational,models=[model] if model else ['qwen3_8b','qwen3_14b'],
        selection_scope='Within selected configurations only; a sole candidate is not evidence of a global hyperparameter optimum'))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=['prepare','offline-check','select','shortlist','run','report','score','analyze','recover-infrastructure']);p.add_argument('--method',choices=METHODS);p.add_argument('--results',type=Path);p.add_argument('--out',type=Path);p.add_argument('--model',choices=['qwen3_8b','qwen3_14b']);p.add_argument('--limit',type=int);p.add_argument('--retry-failed',action='store_true');p.add_argument('--workers',type=int,default=4);a=p.parse_args()
    if a.command=='recover-infrastructure':
        from dev40_recovery import execute
        execute()
    elif a.command=='analyze':
        from dev40_analysis import report
        report()
    elif a.command=='score':
        from dev40_scoring import score
        score(a.model,a.limit,a.retry_failed,a.workers)
    elif a.command=='report':
        from dev40_report import report
        report()
    elif a.command=='run':
        from dev40_runner import main
        main(a)
    elif a.command=='prepare':prepare()
    elif a.command=='shortlist':print(json.dumps(shortlist()))
    elif a.command=='offline-check':offline_check(a.method)
    else:select(a.results,a.out,a.model)
