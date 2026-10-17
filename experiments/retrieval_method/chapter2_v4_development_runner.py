"""Matched full-method development QA before the new formal method is frozen."""
import argparse
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
import os
import sys
from threading import RLock
import time

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT / 'src'))
from chapter2_v2_retrieval_probe import read, save, sha
from chapter2_v2_development_runner import ANSWER_CHECKLIST, DeploymentResponse, token_counter, score
from chapter2_proxy_model_execution import MODELS, run_per_model
from chapter2_knowledge_backends_v4 import METHODS, backend, tool_method, HybridNativeView
from chapter2_qa_backends import NativeBackend
from chapter2_backend_process import BackendProcess, RemoteBackend


def clone_backend(template, lock):
    if template is None:return None
    if isinstance(template, RemoteBackend):return RemoteBackend(template.server)
    if isinstance(template, NativeBackend):
        value = NativeBackend(template.engine, graph=template.graph)
    elif isinstance(template, HybridNativeView):
        value = HybridNativeView(template.bm25, template.e5)
    else:raise ValueError('Backend must isolate per-session event logs')
    value.lock = lock
    return value


def generate(args):
    if args.output.exists():raise FileExistsError('New immutable development cohort required')
    servers = {}
    try:
        for method in args.methods:
            if method != 'none':
                servers[method] = BackendProcess(method, args.resources, args.questions,
                    context_characters=args.context_characters, parent_ratio=args.parent_ratio)
        return generate_with_servers(args, servers)
    finally:
        for server in servers.values():server.close()


def generate_with_servers(args, servers):
    from chapter2_knowledge_input_guard import install
    guard = install(args.questions)
    from chapter2_qwen_routing import routed_client
    from chapter2_autonomous_qa import load_tokenizer
    from principia_core.retrieval.knowledge_agent import AutonomousKnowledgeAgent, ModelBudget, SYSTEM
    from principia_core.retrieval.knowledge_qa import FrozenKnowledgeCorpus, KnowledgeToolSession, KnowledgeBudget
    if args.output.exists():raise FileExistsError('New immutable development cohort required')
    resources = read(args.resources); questions = read(args.questions)
    if any(set(q) != {'id', 'question'} for q in questions) or len({q['id'] for q in questions}) != len(questions):raise ValueError('Unique public questions required')
    corpus = FrozenKnowledgeCorpus(resources['corpus'], resources['corpus_manifest'])
    templates = {method: RemoteBackend(servers[method]) if method != 'none' else None for method in args.methods}
    locks = {method: RLock() for method in args.methods}
    counters = {}; tokenizers = {}
    for model in MODELS:
        raw, tokenizers[model] = load_tokenizer(Path(resources['tokenizer_' + model]), model)
        lock = RLock()
        def count(messages, raw=raw, lock=lock):
            with lock:return raw(messages)
        counters[model] = token_counter(count, args.workload, ANSWER_CHECKLIST)
    model_budget = ModelBudget(output_tokens_per_request=4096, final_output_reserve=4096, output_tokens_total=32768)
    knowledge_budget = KnowledgeBudget()
    files = ['chapter2_v4_development_runner.py', 'chapter2_backend_process.py', 'chapter2_v2_development_runner.py', 'chapter2_proxy_model_execution.py',
        'chapter2_knowledge_backends_v4.py', 'chapter2_knowledge_graph_v4.py', 'chapter2_knowledge_graph_v3.py',
        'chapter2_knowledge_graph_v2.py', 'chapter2_knowledge_graph_retriever.py', 'chapter2_qa_backends.py',
        'chapter2_baseline_native.py', 'chapter2_qwen_local.py', 'chapter2_qwen_routing.py', 'chapter2_qwen_proxy_config.py',
        'chapter2_knowledge_input_guard.py', 'chapter2_autonomous_qa.py', 'candidate_graph_utils.py', 'candidate_hybrid.py']
    paths = [PROJECT / 'experiments/retrieval_method' / name for name in files]
    paths += [PROJECT / 'src/principia_core/retrieval' / name for name in ['knowledge_qa.py', 'knowledge_agent.py']]
    save(args.output / 'protocol.json', dict(schema='matched_development_qa_v4', formal_result=False,
        created_utc=datetime.now(timezone.utc).isoformat(), workload=args.workload, workers_per_model=args.workers_per_model,
        models=list(MODELS), methods=args.methods, question_ids=[q['id'] for q in questions], questions_sha256=sha(args.questions),
        resources_sha256=sha(args.resources), system_prompt=SYSTEM, common_answer_checklist=ANSWER_CHECKLIST,
        embedding_runtime_cache=os.environ.get('HF_HUB_CACHE'), e5_manifest_sha256=sha(Path(resources['e5_manifest'])),
        model_budget=asdict(model_budget), knowledge_budget=asdict(knowledge_budget), tokenizer_bindings=tokenizers,
        input_guard=guard, context_characters=args.context_characters, parent_ratio=args.parent_ratio,
        backend_processes={method: server.receipt for method, server in servers.items()},
        graph_artifacts={name: sha(Path(resources[name])) for name in ('graph_full', 'graph_no_cross', 'graph_no_conditions', 'graph_no_extension')},
        implementation_sha256={str(p.relative_to(PROJECT)): sha(p) for p in paths},
        max_transport_attempts=1, content_retries=0, forced_initial_retrieval=False, scoring_rubric='original formal_v1 source_free_v7',
        none_boundary='No corpus/backend/tools supplied to the no-external-knowledge agent; retrieval engines live in separate deterministic worker processes.',
        comparison_scope='New matched development only; no historical answer is relabeled as this cohort.'))
    jobs = [dict(model=model, method=method, question=q) for q in questions for method in args.methods for model in MODELS]
    statuses = Counter()
    def worker(item):
        model, method, q = item['model'], item['method'], item['question']
        folder = args.output / 'sessions' / model / method / q['id']
        client = DeploymentResponse(routed_client(model, folder / 'requests', workload=args.workload, timeout=args.timeout), model, ANSWER_CHECKLIST)
        current = clone_backend(templates[method], locks[method])
        tools = KnowledgeToolSession(tool_method(method), corpus if current else None, current, knowledge_budget)
        started = time.monotonic()
        result = AutonomousKnowledgeAgent(model, tools, client, counters[model], model_budget).run(q['question'])
        result.update(question=q, development_method=method, formal_result=False, deployment_workload=args.workload,
            protocol_sha256=sha(args.output / 'protocol.json'), native_ranking_events=current.events if current else [], seconds=time.monotonic() - started)
        save(folder / 'result.json', result)
        return result
    def observe(item, result):
        statuses[result['status']] += 1
        print(dict(completed=sum(statuses.values()), planned=len(jobs), model=item['model'], method=item['method'], id=item['question']['id'], status=result['status']), flush=True)
        if result['status'] in {'transport_error', 'http_rejected', 'model_mismatch', 'model_identity_mismatch'}:
            raise RuntimeError('Stop admissions and drain; never reissue a failed request')
    try:run_per_model(jobs, worker, observe, model_of=lambda row: row['model'], workers_per_model=args.workers_per_model)
    except Exception:
        save(args.output / 'stopped.json', dict(planned=len(jobs), completed=sum(statuses.values()), statuses=dict(statuses), requests_reissued=False))
        raise
    save(args.output / 'completion.json', dict(planned=len(jobs), completed=sum(statuses.values()), statuses=dict(statuses), complete=True))


def main():
    p = argparse.ArgumentParser(description=__doc__); sub = p.add_subparsers(dest='command', required=True)
    for command in ('generate', 'score'):
        c = sub.add_parser(command)
        for name in ('resources', 'output'):c.add_argument('--' + name, type=Path, required=True)
        c.add_argument('--workload', choices=['bulk', 'small'], required=True)
        c.add_argument('--workers-per-model', type=int); c.add_argument('--timeout', type=int, default=180)
        if command == 'generate':
            c.add_argument('--questions', type=Path, required=True); c.add_argument('--methods', nargs='+', choices=METHODS,
                default=['bm25', 'e5', 'hybrid', 'none', 'graph', 'no_context', 'adjacent_only', 'parent_blanket'])
            c.add_argument('--context-characters', type=int, default=2400); c.add_argument('--parent-ratio', type=float, default=.5)
        else:
            for name in ('input', 'dataset'):c.add_argument('--' + name, type=Path, required=True)
            c.add_argument('--reuse-scores', type=Path)
    a = p.parse_args(); a.workers_per_model = a.workers_per_model or (16 if a.workload == 'bulk' else 1)
    if not 1 <= a.workers_per_model <= 16 or (a.workload == 'small' and a.workers_per_model != 1):raise ValueError('Invalid deployment concurrency')
    (generate if a.command == 'generate' else score)(a)


if __name__ == '__main__':main()
