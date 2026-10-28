"""Bind final methods, deploy identities, evaluation and Test160 paths offline."""
import runtime_layout as layout
import argparse
from copy import deepcopy
import json
from pathlib import Path
import single_pass_dev40 as s
from central_execution import Registry

ROOT=layout.asset('results')


def prepare():
    if layout.asset('test_manifest').exists():
        return layout.validate_manifest()
    ROOT.mkdir(exist_ok=True)
    dev=s.RUN/'experiments/agentic/dev40'
    summary=s.load(dev/'results/summary.json')
    configs=deepcopy(summary['active_configurations'])
    assert len(configs)==26 and all(c['candidate_parameters'].get('tool_calls',0)<=8 for c in configs)
    decision=s.load(ROOT/'configuration_decision.json') if (ROOT/'configuration_decision.json').exists() else {}
    graph_top=decision.get('agentic_graph_top_slots',10)
    for c in configs:
        if c['method_id']=='graph':c['top_slots']=graph_top
    registry=Registry()
    expected=s.load(dev/'execution.json')['bindings']
    bindings={};adapter_updates=[]
    for rel,digest in expected.items():
        actual=s.sha(s.WORKSPACE/rel)
        if actual!=digest:
            name=Path(rel).name
            if name not in ('chapter2_qwen_local.py','chapter2_qwen_proxy_config.py','chapter2_qwen_routing.py'):
                raise ValueError('Inherited generation binding drift: '+rel)
            old=s.RUN/'experiments/agentic/reused_inputs/runtime_snapshot/retrieval_method'/name
            if s.sha(old)!=digest:raise ValueError('Historical adapter snapshot mismatch')
            bindings[old.relative_to(s.WORKSPACE).as_posix()]=digest
            adapter_updates.append(dict(path=rel,historical_sha256=digest,current_sha256=actual,
                original_snapshot=str(old.relative_to(s.WORKSPACE)),
                reason='Existing unified Qwen routing updates predate finalization; final runner uses registered deployment and newly bound recorded transport. Historical requests/runner unchanged.'))
        bindings[rel]=actual
    required=[s.SPLIT/'split_freeze.json',dev/'candidate_matrix.json',dev/'shortlist.json',
              dev/'results/selected_qwen3_8b.json',dev/'results/selected_qwen3_14b.json',
              dev/'endpoint_migration.json',dev/'reuse.json',s.OUT/'protocol.json',
              s.RUN/'evaluation/judges/protocol.json',s.RUN/'evaluation/judges/operational_use.json',
              s.RUN/'evaluation/judges/audit/results/acceptance.json']
    for name in ('dev40','test160'):
        required += [s.SPLIT/name/p for p in ('model/questions.json','scoring/annotations.json','scoring/evidence.json','dataset.json')]
    required += list(s.HERE.glob('*.py'))+[s.HERE/'judge_prompt.txt',s.HERE/'scoring_rules.json']
    required += list((s.PROJECT/'config/llm').glob('*.yaml'))
    required += list((s.RUN/'data/resources/e5').glob('*'))
    required += list((s.RUN/'data/resources/graphs').glob('*.json'))
    required += [dev/'retrieval_study/protocol.json',dev/'retrieval_study/baseline_options.json']
    if decision:required += [ROOT/'configuration_decision.json']
    required += [s.WORKSPACE/'graduation-thesis-materials/graduation-research'/p for p in ('README.md','OVERVIEW.md','chapters/chapter02.md')]
    for p in required:bindings[p.relative_to(s.WORKSPACE).as_posix()]=s.sha(p)
    qs=s.load(s.SPLIT/'test160/model/questions.json')
    manifest=dict(schema='test160_final_matrix',status='frozen_pending_owner_matrix_confirmation' if decision else 'offline_prepared_pending_Dev_final_decision',
        scope=dict(models=2,methods=13,questions=160,sessions=4160),
        question_file=(s.SPLIT/'test160/model/questions.json').relative_to(s.WORKSPACE).as_posix(),
        scoring_only=dict(annotations=(s.SPLIT/'gold/test160/annotations.json').relative_to(s.WORKSPACE).as_posix(),
                          evidence=(s.SPLIT/'gold/test160/evidence.json').relative_to(s.WORKSPACE).as_posix()),
        single_pass_protocol_file=(s.OUT/'protocol.json').relative_to(s.WORKSPACE).as_posix(),
        single_pass_execution=dict(methods=['graph','bm25','bge_m3'],retrieval_calls=1,query='exact original question',
            query_rewrite=False,model_tools=[],top_slots=decision.get('single_pass_graph_top_slots',10),
            delivered_character_cap=6000,output_tokens=2048,qwen3_8b_suffix='/no_think'),
        configurations=configs,bindings=bindings,
        retrieval_parameters=dict(graph=s.load(dev/'retrieval_study/baseline_options.json'),
            relation_inventory=s.load(dev/'retrieval_study/protocol.json')['relation_inventory'],
            graph_online_filters=dict(ranking_exclude=[],context_exclude=[],natural_language_conditions_only=True),
            graph_ablations=dict(no_cross='Frozen no_cross.json + with_cross=False; compound historical arm',
                no_aliases='Frozen no_aliases.json; traversal retained',no_traversal='ranking lookup/traversal and linked context off; static bonuses preserved',
                anchor_only='Intersect full-arm slots with original anchors; no candidate backfill'),
            bm25=dict(k1=1.2,b=.75,passage_characters=1500,preceding_overlap_lines=4,native_limit=64),
            fusion=dict(method='RRF',k=60,pool=64),
            parent_context='Anchor first; nearest independent containing section/brace <=1200 characters else <=1200 adjacent extra characters',
            bge=s.load(s.RUN/'data/resources/indexes/bge_dense_v1/manifest.json'),
            e5_runtime=s.load(s.RUN/'data/resources/e5/runtime-spec.json'),
            e5_manifest_sha256=s.sha(s.RUN/'data/resources/e5/manifest.json'),
            dedup='Unique original path/line after fixing candidate slots, no backfill; exact original-file hashes verified at read'),
        transport_adapter_updates=adapter_updates,
        deployments={m:registry.resolve(m) for m in ('qwen3_8b','qwen3_14b')},
        deployment_evidence='Same exact deployments used by successful Dev40/Top-5 requests; API model identity checked for every response. Provider internal version is only as observable, not assumed.',
        execution=dict(mode='Agentic',tool_calls=8,top_slots_default=10,one_character_cap=6000,total_character_cap=24000,
            combined_tokens=32768,input_tokens_per_request=30720,output_tokens_per_request=2048,
            input_tokens_total=196608,output_tokens_total=16384,final_output_reserve=2048,temperature=0,
            qwen3_8b_concurrency=8,qwen3_14b_concurrency=20,automatic_generation_retries=0,read_timeout_seconds=600,
            original_question_only_as_initial_input=True,tools_selected_by_model=True),
        scoring=dict(judges=list(s.JUDGES),profiles={j:registry.judge_profile(j) for j in s.JUDGES},
            prompt_sha256=s.sha(s.HERE/'judge_prompt.txt'),rules_sha256=s.sha(s.HERE/'scoring_rules.json'),
            schema_sha256=s.sha(s.HERE/'judge_contract.py'),gpt_max_completion_tokens=8192,
            combined_cap=32768,concurrency_per_judge=2,additional_attempts_per_invalid_answer=3,
            retry_http=[429,500,502,503,504],backoff_seconds=[5,20],read_timeout_seconds=600,
            unknown_timeout='Reconcile request ledger and saved response; unresolved timeout held, never blindly resend',
            invalid_response='Only explicit structural failure retried within finite cap; all raw attempts retained',
            original_human_audit_passed=False,measurement_limitation='Original independent audit failed prespecified thresholds; later owner operational authorization is not audit acceptance'),
        metrics=dict(primary='Mean over 160 answers of per-answer two-judge mean EAS_arith',
            K='Unweighted arithmetic mean of required-point scores {0,.25,.5,.75,1}',
            EAS_arith='100*(K+F+A)/3 if conditional; 100*(K+F)/2 otherwise',
            EAS_geo='100*(K*F*A)^(1/3) if conditional; 100*(K*F)^(1/2) otherwise; no smoothing',
            failures='Generation failure contributes zero EAS on fixed 160 denominator',
            unknown='No substituted labels; unavailable point estimate remains unknown; retain full-denominator lower/upper bounds',
            dual='Mean per-answer metrics; never geometrically aggregate across judges or drop missing answers',
            auxiliary=['K','F','A','EAS_geo','Strict','required evidence line/span recall','tool adoption','actual characters','observed tokens']),
        supplemental=decision.get('test_supplements',dict(single_pass='Three independent backends x 2 models x 160 = 960 sessions, pending final Dev assessment',relation_mechanisms='No inclusion decision before final Dev results')),
        output_paths=dict(generation='test160/generation/<config_id>/<question_id>',scoring='test160/scoring/<judge>/<sample_id>',
            statistics='test160/analysis',archive='00_archive',ledger='test160/request_ledger.jsonl'),
        pipeline=dict(generate='test160_runner.py execute --authorization <owner-confirmed-json>',
            generate_single_pass='test160_runner.py execute-single-pass --authorization <owner-confirmed-json>',
            offline='test160_runner.py check',score='test160_evaluation.py score --authorization <owner-confirmed-json>',
            statistics='test160_evaluation.py analyze --authorization <owner-confirmed-json>',
            archive='dev40_assets.py verify; never move manifest-bound evidence'),
        tasks=[dict(config_id=c['config_id'],model=c['model_key'],method=c['method_id'],question_id=q['id']) for c in configs for q in qs],
        owner_confirmation_pending=True,test160_started=False,model_requests_sent=0)
    if decision:manifest['decision_sha256']=s.sha(ROOT/'configuration_decision.json')
    s.save(ROOT/'test160_manifest.json',manifest)
    s.save(ROOT/'test160_manifest.sha256.json',dict(sha256=s.sha(ROOT/'test160_manifest.json'),file='test160_manifest.json'))
    print(json.dumps(dict(configurations=len(configs),sessions=len(manifest['tasks']),bindings=len(bindings),status=manifest['status'],test160_started=False)))
    return manifest


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('command',choices=['prepare']);a=p.parse_args();prepare()
