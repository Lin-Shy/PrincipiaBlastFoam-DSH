"""Execute the newly frozen complete matrix with one shared per-model scheduler."""
import argparse
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import sys
from threading import RLock
import time

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT / 'src'))
from chapter2_full_protocol import validate, verify_sources, pending_jobs, method_key
from chapter2_v2_retrieval_probe import read, save, sha
from chapter2_v2_development_runner import ANSWER_CHECKLIST, DeploymentResponse, token_counter
from chapter2_backend_process import BackendProcess, RemoteBackend
from chapter2_proxy_model_execution import MODELS, run_per_model


def artifact_check(plan, resources, aliases):
    for name in aliases:
        path = Path(resources[name])
        if name.startswith('tokenizer_'):path = path / 'artifact-binding.json'
        if sha(path) != plan['artifacts_sha256'][name]:raise ValueError('Formal artifact changed: ' + name)


def protocol(plan, plan_path, resources_path, diagnostic):
    from principia_core.retrieval.knowledge_agent import SYSTEM
    if sha_bytes(SYSTEM) != plan['system_prompt_sha256'] or ANSWER_CHECKLIST != plan['common_answer_checklist']:
        raise ValueError('Common prompt differs from the frozen complete activity')
    return dict(schema='complete_knowledge_qa_generation_v4', formal_result=True,
        plan_sha256=sha(plan_path), resources_sha256=sha(resources_path), phase='diagnostic' if diagnostic else 'retrieval',
        workload='bulk', workers_per_model=16, models=list(MODELS), model_budget=plan['model_budget'],
        common_answer_checklist=ANSWER_CHECKLIST, system_prompt=SYSTEM,
        source_sha256=plan['runtime_source_sha256'], artifacts_sha256=plan['artifacts_sha256'],
        forced_initial_retrieval=False, transport_attempts=1, content_retries=0,
        retrieval_isolation='One guarded deterministic worker per retrieval method; no LLM in these workers.',
        none_boundary='No corpus/backend/tools supplied to the none agent.',
        privileged_input=diagnostic, diagnostic_boundary='Only confirmed necessary originals in separate phase; no ordinary retrieval use.')


def sha_bytes(value):return hashlib.sha256(value.encode('utf-8')).hexdigest()


def execute(args, plan, resources, servers):
    from chapter2_autonomous_qa import load_tokenizer
    from chapter2_qwen_routing import routed_client
    from principia_core.retrieval.knowledge_agent import AutonomousKnowledgeAgent, ModelBudget
    from principia_core.retrieval.knowledge_qa import FrozenKnowledgeCorpus, KnowledgeToolSession, KnowledgeBudget
    public = Path(resources['questions'])
    if args.diagnostic:
        from chapter2_complete_material_qa import install_diagnostic_guard, validate_pack, run_diagnostic
        guard = install_diagnostic_guard(resources['materials'], resources['review_receipt'], public)
    else:
        from chapter2_knowledge_input_guard import install
        guard = install(public)
    aliases = ['questions','corpus_manifest','source_map','tokenizer_qwen3-8b','tokenizer_qwen3-14b']
    aliases += ['materials','review_receipt'] if args.diagnostic else ['e5_manifest','graph_full','graph_no_cross','graph_no_conditions','graph_no_extension']
    artifact_check(plan, resources, aliases)
    questions = read(public)
    if any(set(q) != {'id','question'} for q in questions) or [q['id'] for q in questions] != plan['test_ids']:
        raise ValueError('Exact complete public test cohort and order required')
    by_id = {q['id']:q for q in questions}
    corpus = FrozenKnowledgeCorpus(resources['corpus'], resources['corpus_manifest'])
    if read(Path(resources['source_map']))['files'] != corpus.hashes:raise ValueError('Authority source map differs')
    pack = None
    if args.diagnostic:
        values, _ = validate_pack(Path(resources['materials']),Path(resources['review_receipt']),questions,corpus)
        pack = {q['id']:q for q in values}
        if set(pack) != set(plan['diagnostic_ids']):raise ValueError('Privileged diagnostic cohort changed')
    value = protocol(plan,args.plan,args.resources,args.diagnostic)
    protocol_path = args.output / ('diagnostic-protocol.json' if args.diagnostic else 'protocol.json')
    if protocol_path.exists():
        if read(protocol_path) != value:raise ValueError('Existing formal protocol changed')
    else:
        if args.output.exists() and any(args.output.glob('**/result.json')):
            raise ValueError('Results without a bound formal protocol')
        save(protocol_path,value)
    binding = sha(protocol_path)
    jobs, existing = pending_jobs(plan,args.output,by_id,binding,diagnostic=args.diagnostic)
    if existing and not args.continue_unattempted:raise ValueError('Explicit continuation required; terminal failures will be preserved')
    counters, tokenizers = {}, {}
    for model in MODELS:
        raw, tokenizers[model] = load_tokenizer(Path(resources['tokenizer_'+model]),model)
        lock = RLock()
        def count(messages,raw=raw,lock=lock):
            with lock:return raw(messages)
        counters[model] = token_counter(count,'bulk',ANSWER_CHECKLIST)
    budget = ModelBudget(**plan['model_budget'])
    statuses = Counter(r['status'] for r in existing)
    save(args.receipt/'start.json',dict(created_utc=datetime.now(timezone.utc).isoformat(),
        plan_sha256=sha(args.plan), protocol_sha256=binding, resumed_results=len(existing),
        unattempted=len(jobs), existing_terminal_failures=sum(r['status']!='answered' for r in existing),
        input_guard=guard, tokenizers=tokenizers, workers={k:s.receipt for k,s in servers.items()},
        physical_requests_reissued=False))
    if args.prepare_only:
        save(args.receipt/'preflight.json',dict(formal_result=False,model_calls=0,planned=len(existing)+len(jobs),
            protocol_sha256=binding,artifact_metadata_verified=True,input_guard=guard))
        return
    def worker(item):
        cell, q = item['cell'], item['question']; model = cell['model']
        folder = args.output / cell['id'] / 'sessions' / q['id']
        client = DeploymentResponse(routed_client(model,folder/'requests',workload='bulk',settings_path=args.proxy_settings,timeout=args.timeout),model,ANSWER_CHECKLIST)
        started = time.monotonic()
        if args.diagnostic:
            result = run_diagnostic(pack[q['id']],model,client,counters[model],budget)
        else:
            current = RemoteBackend(servers[method_key(cell)]) if cell['method'] != 'none' else None
            kb = KnowledgeBudget(tool_calls=cell['tool_calls'],tool_characters=plan['knowledge_per_result_characters'],total_characters=cell['knowledge_characters'])
            tools = KnowledgeToolSession(cell['method'],corpus if current else None,current,kb)
            result = AutonomousKnowledgeAgent(model,tools,client,counters[model],budget).run(q['question'])
            result['native_ranking_events'] = current.events if current else []
        result.update(question=q, formal_result=True, formal_cell_id=cell['id'], protocol_sha256=binding,
            plan_sha256=sha(args.plan), seconds=time.monotonic()-started)
        save(folder/'result.json',result)
        save(folder/'result-binding.json',dict(result_sha256=sha(folder/'result.json'),protocol_sha256=binding,cell_id=cell['id']))
        return result
    planned = len(existing)+len(jobs)
    def observe(item,result):
        statuses[result['status']] += 1
        print(dict(completed=sum(statuses.values()),planned=planned,cell=item['cell']['id'],id=item['question']['id'],status=result['status']),flush=True)
        if result['status'] in {'transport_error','http_rejected','model_mismatch','model_identity_mismatch'}:
            raise RuntimeError('Stop new admissions and drain; preserve all terminal records without replay')
    try:
        run_per_model(jobs,worker,observe,model_of=lambda row:row['model'],workers_per_model=16)
    except Exception:
        save(args.receipt/'stopped.json',dict(planned=planned,completed=sum(statuses.values()),statuses=dict(statuses),physical_requests_reissued=False))
        raise
    save(args.receipt/'completion.json',dict(complete=True,planned=planned,completed=sum(statuses.values()),statuses=dict(statuses),protocol_sha256=binding))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('plan','resources','output','receipt','proxy-settings'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--diagnostic',action='store_true')
    parser.add_argument('--prepare-only',action='store_true')
    parser.add_argument('--continue-unattempted',action='store_true')
    parser.add_argument('--timeout',type=int,default=180)
    args = parser.parse_args()
    if args.receipt.exists():raise FileExistsError('New immutable execution receipt required')
    plan = read(args.plan);validate(plan);verify_sources(plan,PROJECT)
    resources = read(args.resources)
    servers = {}
    try:
        if not args.diagnostic:
            keys = list(dict.fromkeys(method_key(c) for c in plan['cells'] if c['method'] not in {'none','complete_material_diagnostic'}))
            for key in keys:
                servers[key] = BackendProcess(key,args.resources,Path(resources['questions']),
                    context_characters=plan['context_characters'],parent_ratio=plan['parent_ratio'],context_policy=plan['context_policy'])
        execute(args,plan,resources,servers)
    finally:
        for server in servers.values():server.close()


if __name__ == '__main__':main()
