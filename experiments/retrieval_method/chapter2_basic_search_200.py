"""Fresh full-bank basic-search baseline, separately frozen for 8B and 14B."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
import random
from threading import RLock
import time
import regex

from chapter2_optimization_200 import PROJECT, DATASET, RESOURCES, read, save, sha
from chapter2_autonomous_qa import load_tokenizer
from chapter2_qa_deployment import DeploymentResponse, token_counter, ANSWER_CHECKLIST
from chapter2_qwen_routing import routed_client
from principia_core.retrieval.knowledge_qa import FrozenKnowledgeCorpus, KnowledgeBudget
from principia_core.retrieval.knowledge_agent import ModelBudget
from chapter2_basic_search_tools import BasicSearchSession, basic_specs
from chapter2_basic_search_agent import BasicSearchAgent
from chapter2_basic_search_audit import audit_session

ARM = 'basic_search'
CHECKLIST = ANSWER_CHECKLIST.replace('"name":"search","arguments":{"query":"具体标识与所需含义"}',
    '"name":"grep","arguments":{"pattern":"具体英文标识"}')
SOURCES = ['chapter2_basic_search_200.py', 'chapter2_basic_search_tools.py', 'chapter2_basic_search_agent.py',
    'chapter2_basic_search_audit.py', 'chapter2_basic_search_analysis.py']


def prepare(root, reference, model):
    if root.exists():
        raise FileExistsError(root)
    original = read(reference/'protocol.json')
    p = deepcopy(original)
    for key in ['reused_baselines', 'e5_resources', 'construction_graph_sha256', 'graph_method']:
        p.pop(key, None)
    p.update(schema='publication_200_basic_search_extension_v1', status='frozen_before_generation',
        answer_model=model, arms=[ARM], comparison_arms=[ARM], generation_sessions=200, graphs={}, e5_resources={},
        workers_per_arm=8, max_concurrent_answer_requests=8, baseline_reuse=False,
        model_budget=asdict(ModelBudget()), knowledge_budget=asdict(KnowledgeBudget()),
        common_answer_checklist=CHECKLIST, basic_tool_specs=basic_specs(),
        tokenizer_model=model, tokenizer_sha256=sha(RESOURCES/'tokenizers'/model/'artifact-binding.json'),
        reference_protocol_sha256=sha(reference/'protocol.json'),
        graph_selection='Previously accepted graph unchanged; this activity has no graph access',
        baseline_definition='Ordinary glob, line-regex grep, original read_source; same 479-file corpus; lexical path/line order; no graph, generated aliases, BM25/E5/hybrid, relevance scoring or persistent index',
        consumer='Same bounded action loop; only tool specs differ. Common checklist example substitutes grep/pattern for unavailable search/query. All other policy and limits identical.',
        dependencies=dict(regex_version=regex.__version__, regex_extension_sha256=sha(Path(regex._regex.__file__))),
        batch_boundary='Baseline added after observing completed five-method results. Fresh 200-question baseline only, compared to unchanged original receipts; not a simultaneous rerun.',
        statistics=dict(primary='end_to_end_valid_answer_score', secondary='complete_valid_answer_rate',
            comparison_families=dict(primary=['graph vs '+m for m in ['bm25','e5','hybrid','none',ARM]],
                ablation=['graph vs graph_no_cross', 'graph vs graph_no_aliases']),
            multiplicity='Holm separately within extended five-comparison main family and unchanged two-comparison ablation family, separately per answer model',
            paired_unit='24 predefined knowledge groups', seed=20261019, bootstrap_replicates=10000,
            unknowns='Unchanged frozen rubric and interval-aware conservative sign test',
            practical_difference_percentage_points=5))
    questions = read(DATASET/'model/questions.json')
    assert len(questions) == 200 and all(set(q) == {'id','question'} for q in questions)
    load_tokenizer(RESOURCES/'tokenizers'/model, model)
    save(root/'public-questions.json', questions)
    p['public_questions_sha256'] = sha(root/'public-questions.json')
    adopted = root/'provenance/adopted-chapter02.md'
    adopted.parent.mkdir(parents=True, exist_ok=True)
    adopted.write_bytes((PROJECT.parent/'graduation-thesis-materials/graduation-research/chapters/chapter02.md').read_bytes())
    p['design_sha256'] = sha(adopted)
    p['reference_analysis'] = dict(path=str((reference/'analysis_001').resolve()),
        sha256={name:sha(reference/'analysis_001'/name) for name in ['summary.json','session-metrics.json']})
    bindings = dict(original['implementation_sha256'])
    for name in SOURCES:
        source = Path(__file__).with_name(name)
        bindings[source.relative_to(PROJECT).as_posix()] = sha(source)
    for rel, digest in bindings.items():
        source = PROJECT/rel
        if sha(source) != digest:
            raise ValueError('Existing frozen source drift: '+rel)
        target = root/'runtime'/rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
    p['implementation_sha256'] = bindings
    save(root/'user-authorization.json', dict(endpoint=read(reference/'user-authorization.json')['endpoint'],
        model=model, user_instruction='基础工具就是没有其他专用检索方法，但是有普通的搜索工具比如grep和glob，这个可以作为对照方法之一。',
        scope='Add basic-search baseline to the already authorized full-200 8B/14B comparison and anonymous established 14B scoring; same questions, public source corpus and destination',
        preceding_export_authorizations=['我同意明确覆盖新200题及检索原文发送至代理8B，继续完成正式回答', '授权上述14B回答实验和评分外发'],
        generation_sessions=200, max_transport_attempts=1, content_retries=0, targeted_reviews=0))
    p['authorization_sha256'] = sha(root/'user-authorization.json')
    save(root/'protocol.json', p)
    print(dict(model=model, sessions=200, protocol_sha256=sha(root/'protocol.json')), flush=True)


def verify(root):
    p = read(root/'protocol.json')
    assert p['arms'] == [ARM] and p['answer_model'] in {'qwen3-8b','qwen3-14b'}
    for rel, digest in p['implementation_sha256'].items():
        if sha(PROJECT/rel) != digest or sha(root/'runtime'/rel) != digest:
            raise ValueError('Frozen implementation drift: '+rel)
    for name, digest in p['source_resources'].items():
        assert sha(RESOURCES/name) == digest
    assert sha(root/'public-questions.json') == p['public_questions_sha256']
    assert sha(DATASET/'model/questions.json') == p['questions_sha256']
    assert sha(RESOURCES/'tokenizers'/p['answer_model']/'artifact-binding.json') == p['tokenizer_sha256']
    assert regex.__version__ == p['dependencies']['regex_version']
    assert sha(Path(regex._regex.__file__)) == p['dependencies']['regex_extension_sha256']
    assert sha(root/'user-authorization.json') == p['authorization_sha256']
    return p


def answer(root):
    p = verify(root)
    from chapter2_knowledge_input_guard import install
    install(DATASET/'model/questions.json')
    model = p['answer_model']
    raw, _ = load_tokenizer(RESOURCES/'tokenizers'/model, model)
    lock = RLock()
    def count(messages):
        with lock:
            return raw(messages)
    counter = token_counter(count, 'bulk', CHECKLIST)
    corpus = FrozenKnowledgeCorpus(RESOURCES/'corpus', RESOURCES/'corpus-manifest.json')
    questions = read(root/'public-questions.json')
    random.Random(p['seed']).shuffle(questions)
    def worker(q):
        folder = root/'generation'/ARM/q['id']
        target = folder/'result.json'
        if target.exists():
            old = read(target)
            assert old['protocol_sha256'] == sha(root/'protocol.json')
            return old['status']
        if (folder/'requests').exists():
            raise ValueError('Unresolved original request retained; no automatic replay')
        client = DeploymentResponse(routed_client(model, folder/'requests', workload='bulk', timeout=180), model, CHECKLIST)
        tools = BasicSearchSession(corpus, KnowledgeBudget(**p['knowledge_budget']))
        started = time.monotonic()
        result = BasicSearchAgent(model, tools, client, counter, ModelBudget(**p['model_budget'])).run(q['question'])
        result.update(id=q['id'], arm=ARM, answer_model=model, protocol_sha256=sha(root/'protocol.json'),
            seconds=time.monotonic()-started, delivered_lines=[dict(path=path,line=n) for path,n in sorted(tools.delivered_lines)])
        # Invalid Unicode is a failed delivered answer, with original response
        # retained in the request and turn; never repair its answer content.
        if result['status'] == 'answered':
            try:
                result['answer'].encode('utf-8')
            except UnicodeError:
                result.update(status='invalid_unicode_output', answer=None, references=None)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('x', encoding='utf-8') as f:
            f.write(json.dumps(result, ensure_ascii=True, indent=2)+'\n')
        return result['status']
    counts = Counter()
    with ThreadPoolExecutor(max_workers=p['workers_per_arm']) as pool:
        for done, future in enumerate(as_completed([pool.submit(worker,q) for q in questions]),1):
            counts[future.result()] += 1
            if done % 10 == 0:
                print(model,done,dict(counts),flush=True)
    save(root/'completion'/(ARM+'.json'),dict(arm=ARM,sessions=done,statuses=dict(counts),protocol_sha256=sha(root/'protocol.json'),
        results_sha256={q['id']:sha(root/'generation'/ARM/q['id']/'result.json') for q in questions}))


def audit(root):
    p = verify(root)
    questions = read(root/'public-questions.json')
    completion = read(root/'completion'/(ARM+'.json'))
    assert completion['sessions'] == 200 and completion['protocol_sha256'] == sha(root/'protocol.json')
    cache, bindings, physical, usage, statuses, rows = {}, {}, Counter(), Counter(), Counter(), []
    corpus = FrozenKnowledgeCorpus(RESOURCES/'corpus', RESOURCES/'corpus-manifest.json')
    for q in questions:
        value = audit_session(root,ARM,q['id'],q['question'],p,cache)
        assert value['result_sha256'] == completion['results_sha256'][q['id']]
        bindings[q['id']] = value['result_sha256']
        physical.update(value['request_statuses']); usage.update(value['known_usage']); statuses[value['status']] += 1
        result = read(root/'generation'/ARM/q['id']/'result.json')
        # Deterministic tools are replayed locally, never a model request.
        tools = BasicSearchSession(corpus,KnowledgeBudget(**p['knowledge_budget']))
        for event in result['tool_events']:
            assert tools.execute(event['name'],event['arguments']) == event['response'], 'Tool replay drift'
        rows.append(dict(arm=ARM,id=q['id'],question=q['question'],status=result['status'],answer=result['answer'],
            references=result['references'],references_delivered=result.get('references_delivered'),result_sha256=value['result_sha256']))
    with (root/'answers.jsonl').open('x',encoding='utf-8') as f:
        for row in rows:
            f.write(json.dumps(row,ensure_ascii=True)+'\n')
    assert dict(statuses) == completion['statuses']
    save(root/'generation-audit.json',dict(generation_complete=True,registered=200,closed=200,answered=statuses['answered'],
        statuses=dict(statuses),physical_requests=sum(physical.values()),request_statuses=dict(physical),known_usage=dict(usage),
        executor_concurrency_bound=8,source_and_tool_replay_verified=True,results_sha256=bindings,
        answers_jsonl_sha256=sha(root/'answers.jsonl'),protocol_sha256=sha(root/'protocol.json'),audit_source_sha256=sha(Path(__file__))))
    print(dict(model=p['answer_model'],statuses=dict(statuses),requests=sum(physical.values())),flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['prepare','answer','audit'])
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--reference', type=Path)
    parser.add_argument('--model', choices=['qwen3-8b','qwen3-14b'])
    args = parser.parse_args()
    if args.command == 'prepare':
        prepare(args.root.resolve(),args.reference.resolve(),args.model)
    else:
        globals()[args.command](args.root.resolve())
