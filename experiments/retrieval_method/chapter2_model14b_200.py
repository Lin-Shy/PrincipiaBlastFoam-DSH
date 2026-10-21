"""Full-bank 14B answer experiment on the accepted Chapter 2 graph.

Keep the completed 8B sources and receipts immutable. Reuse their consumer,
tools, budgets and judge rubric; bind the 14B tokenizer and a fresh 1400 grid.
Generation and judging run sequentially to share the proxy's 16-worker cap.
"""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
import os
from pathlib import Path
import random
import subprocess
import sys
from threading import RLock
import time

from chapter2_optimization_200 import PROJECT, DATASET, RESOURCES, read, save, sha, engine
from chapter2_selected_graph_200 import backend as graph_backend
from chapter2_publication_200 import verify
from chapter2_autonomous_qa import load_tokenizer
from chapter2_common_qa_interface import NeutralToolClient, neutral_messages
from chapter2_qa_deployment import DeploymentResponse, token_counter, ANSWER_CHECKLIST
from chapter2_qwen_routing import routed_client
from principia_core.retrieval.knowledge_agent import AutonomousKnowledgeAgent, ModelBudget
from principia_core.retrieval.knowledge_qa import FrozenKnowledgeCorpus, KnowledgeToolSession, KnowledgeBudget

ARMS = ['graph', 'bm25', 'e5', 'hybrid', 'none', 'graph_no_cross', 'graph_no_aliases']
PROFILES = {'graph': 'selected', 'graph_no_cross': 'no_cross', 'graph_no_aliases': 'no_aliases'}
MODEL = 'qwen3-14b'


def prepare(root, reference):
    if root.exists():
        raise FileExistsError('A fresh immutable 14B activity is required')
    original = verify(reference)
    p = deepcopy(original)
    p.pop('reused_baselines', None)
    p.update(schema='publication_200_answer_model14b_v1', status='frozen_before_generation',
        arms=ARMS, comparison_arms=ARMS, generation_sessions=1400, answer_model=MODEL,
        workers_per_arm=2, max_concurrent_answer_requests=14,
        reference_8b_protocol_sha256=sha(reference/'protocol.json'),
        baseline_reuse=False, graph_selection='User accepted the selected full graph as the official Chapter 2 method; fixed before this 14B run',
        tokenizer_sha256=sha(RESOURCES/'tokenizers/qwen3-14b/artifact-binding.json'),
        tokenizer_model=MODEL,
        model_comparison_boundary='14B is a fresh complete seven-arm batch. 8B retains its own recorded batch identities; no answers or judgments are relabeled across answer models.',
        judge_same_model_as_answer=True,
        judge_boundary='Anonymous independent API calls use the established 14B rubric. Same model family and size may introduce evaluation bias; no independent human accuracy claim.')
    questions = read(DATASET/'model/questions.json')
    if len(questions) != 200 or any(set(q) != {'id', 'question'} for q in questions):
        raise ValueError('Exact public-only 200-question bank required')
    # Tokenizer is validated locally before any external call.
    load_tokenizer(RESOURCES/'tokenizers/qwen3-14b', MODEL)
    for name in ['selected.json', 'no_cross.json', 'no_aliases.json', 'manifest.json']:
        target = root/'graphs'/name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((reference/'graphs'/name).read_bytes())
    save(root/'public-questions.json', questions)
    adopted = root/'provenance/adopted-chapter02.md'
    adopted.parent.mkdir(parents=True, exist_ok=True)
    adopted.write_bytes((PROJECT.parent/'graduation-thesis-materials/graduation-research/chapters/chapter02.md').read_bytes())
    p['design_sha256'] = sha(adopted)
    p['public_questions_sha256'] = sha(root/'public-questions.json')
    bindings = dict(original['implementation_sha256'])
    for name in ['chapter2_model14b_200.py', 'chapter2_model14b_generation_audit.py']:
        source = Path(__file__).with_name(name)
        bindings[source.relative_to(PROJECT).as_posix()] = sha(source)
    for rel, digest in bindings.items():
        source = PROJECT/rel
        if sha(source) != digest:
            raise ValueError('Source drift: '+rel)
        target = root/'runtime'/rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
    p['implementation_sha256'] = bindings
    endpoint = read(reference/'user-authorization.json')['endpoint']
    save(root/'user-authorization.json', dict(endpoint=endpoint, model=MODEL,
        user_instruction='14B 实验可以补充了，32B的才是需要等待我补充',
        scope='Full 200-question seven-arm 14B answer experiment, natural questions and actually retrieved originals to the configured proxy; established anonymous 14B scoring follows generation',
        transport_attempts=1, content_retries=0, max_concurrent_requests=14))
    p['authorization_sha256'] = sha(root/'user-authorization.json')
    save(root/'protocol.json', p)
    print(dict(model=MODEL, sessions=1400, protocol_sha256=sha(root/'protocol.json')), flush=True)


def answer(root, arm):
    p = verify(root)
    if p['answer_model'] != MODEL or p['arms'] != ARMS or arm not in ARMS:
        raise ValueError('14B grid identity drift')
    from chapter2_knowledge_input_guard import install
    install(DATASET/'model/questions.json')
    if sha(RESOURCES/'tokenizers/qwen3-14b/artifact-binding.json') != p['tokenizer_sha256']:
        raise ValueError('Answer tokenizer binding drift')
    raw, _ = load_tokenizer(RESOURCES/'tokenizers/qwen3-14b', MODEL)
    lock = RLock()
    def count(messages):
        with lock:
            return raw(neutral_messages(messages))
    counter = token_counter(count, 'bulk', ANSWER_CHECKLIST)
    corpus = None
    selected = None
    method = arm
    if arm != 'none':
        corpus = FrozenKnowledgeCorpus(RESOURCES/'corpus', RESOURCES/'corpus-manifest.json')
        if arm in PROFILES:
            method = 'graph'
            selected = graph_backend(root/'graphs', PROFILES[arm])
        else:
            if arm in {'e5', 'hybrid'}:
                for name, digest in p['e5_resources'].items():
                    if sha(RESOURCES/'e5'/name) != digest:
                        raise ValueError('E5 resource drift')
                os.environ['HF_HUB_CACHE'] = read(RESOURCES/'e5/runtime-spec.json')['cache_folder']
                os.environ['HF_HUB_OFFLINE'] = '1'
                os.environ['TRANSFORMERS_OFFLINE'] = '1'
            selected = engine(arm, None)
    questions = read(root/'public-questions.json')
    random.Random(p['seed']).shuffle(questions)
    def worker(q):
        folder = root/'generation'/arm/q['id']
        target = folder/'result.json'
        if target.exists():
            existing = read(target)
            if existing['protocol_sha256'] != sha(root/'protocol.json'):
                raise ValueError('Session protocol drift')
            return existing['status']
        if (folder/'requests').exists():
            raise ValueError('Unresolved session retained; automatic replay forbidden')
        client = DeploymentResponse(NeutralToolClient(routed_client(MODEL, folder/'requests', workload='bulk', timeout=180)), MODEL, ANSWER_CHECKLIST)
        tools = KnowledgeToolSession(method, corpus, selected, KnowledgeBudget(**p['knowledge_budget']))
        started = time.monotonic()
        result = AutonomousKnowledgeAgent(MODEL, tools, client, counter, ModelBudget(**p['model_budget'])).run(q['question'])
        result.update(id=q['id'], arm=arm, answer_model=MODEL, protocol_sha256=sha(root/'protocol.json'),
            seconds=time.monotonic()-started, delivered_lines=[dict(path=path, line=n) for path, n in sorted(tools.delivered_lines)])
        save(target, result)
        return result['status']
    counts = Counter()
    with ThreadPoolExecutor(max_workers=p['workers_per_arm']) as pool:
        for done, future in enumerate(as_completed([pool.submit(worker, q) for q in questions]), 1):
            counts[future.result()] += 1
            if done % 10 == 0:
                print(arm, done, dict(counts), flush=True)
    save(root/'completion'/(arm+'.json'), dict(arm=arm, sessions=done, statuses=dict(counts),
        protocol_sha256=sha(root/'protocol.json'),
        results_sha256={q['id']:sha(root/'generation'/arm/q['id']/'result.json') for q in questions}))


def run(root):
    p = verify(root)
    def worker(arm):
        if (root/'completion'/(arm+'.json')).exists():
            return arm, 0
        log = root/'logs'/(arm+'.log')
        log.parent.mkdir(exist_ok=True)
        with log.open('a', encoding='utf-8') as output:
            completed = subprocess.run([sys.executable, '-X', 'utf8', str(Path(__file__).resolve()),
                'answer', '--root', str(root.resolve()), '--arm', arm], cwd=PROJECT, stdout=output, stderr=subprocess.STDOUT)
        print(arm, 'exit', completed.returncode, flush=True)
        return arm, completed.returncode
    with ThreadPoolExecutor(max_workers=7) as pool:
        results = dict(pool.map(worker, p['arms']))
    save(root/'generation-controller-completion.json', dict(arms=results, complete=all(v == 0 for v in results.values()),
        protocol_sha256=sha(root/'protocol.json')))
    if any(results.values()):
        raise SystemExit(1)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['prepare', 'answer', 'run'])
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--reference', type=Path)
    parser.add_argument('--arm', choices=ARMS)
    args = parser.parse_args()
    if args.command == 'prepare':
        prepare(args.root.resolve(), args.reference.resolve())
    elif args.command == 'answer':
        answer(args.root.resolve(), args.arm)
    else:
        run(args.root.resolve())
