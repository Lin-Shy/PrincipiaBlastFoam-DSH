"""Gold-isolated development retrieval; separate offline evaluation command."""
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import sys
import time

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT/'src'))


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)


def retrieve(args):
    from chapter2_knowledge_input_guard import install
    guard = install(args.questions)
    from chapter2_knowledge_graph_retriever import KnowledgeGraphRetriever
    from chapter2_knowledge_graph_v2 import EvidenceGraphV2
    from chapter2_qa_backends import NativeBackend
    from principia_core.retrieval.knowledge_qa import FrozenKnowledgeCorpus, KnowledgeToolSession, KnowledgeBudget
    if args.output.exists():
        raise FileExistsError('New development revision required')
    questions = read(args.questions)
    if any(set(q) != {'id', 'question'} for q in questions):
        raise ValueError('Production input must contain only public id/question')
    corpus = FrozenKnowledgeCorpus(args.corpus, args.manifest)
    engines = {
        'graph_v1': KnowledgeGraphRetriever(args.graph, args.corpus, corpus_manifest=args.source_map),
        'typed_whole': EvidenceGraphV2(args.graph, args.corpus, corpus_manifest=args.source_map, evidence_policy='whole'),
        'typed_compact': EvidenceGraphV2(args.graph, args.corpus, corpus_manifest=args.source_map),
        'typed_hierarchy_compact': EvidenceGraphV2(args.graph_v2, args.corpus, corpus_manifest=args.source_map),
    }
    backends = {name: NativeBackend(engine, graph=True) for name, engine in engines.items()}
    from chapter2_baseline_native import NoGraphBM25
    backends['bm25_current'] = NativeBackend(NoGraphBM25(args.corpus, args.source_map))
    backends = {name: backend for name,backend in backends.items() if name in args.methods}
    bindings = {str(p):sha(p) for p in [args.questions, args.graph, args.graph_v2, args.manifest, args.source_map,
        Path(__file__), PROJECT/'experiments/retrieval_method/chapter2_knowledge_graph_v2.py',
        PROJECT/'experiments/retrieval_method/chapter2_knowledge_graph_retriever.py',
        PROJECT/'experiments/retrieval_method/chapter2_baseline_native.py']}
    save(args.output/'protocol.json', dict(schema='development_public_query_retrieval_probe_v2',
        formal_result=False, questions=len(questions), model_calls=0, input_guard=guard,
        input_sha256=bindings, methods=list(backends), query_policy='identical unmodified public natural question',
        budgets=[6000,12000,24000], top_k=[1,3,5,10],
        limitations=['Pure public-query retrieval diagnosis; not an autonomous QA performance result.',
            'BM25 current source identity is recorded; not a replay of historical frozen rankings.']))
    for method, backend in backends.items():
        for question in questions:
            started = time.monotonic()
            packet, stats = backend.ranked(question['question'], 64)
            candidates = [dict(path=r['path'], start=s['start'], end=s['end'])
                for r in packet['items'] for s in r['ranges']]
            deliveries = {}
            for cap in [6000,12000,24000]:
                tools = KnowledgeToolSession('graph' if method != 'bm25_current' else 'bm25', corpus, backend,
                    KnowledgeBudget(tool_calls=1, tool_characters=cap, total_characters=cap))
                # Use the already computed native ranking so token/latency
                # observations cannot accidentally include repeated searches.
                encoded, lines = tools._deliver(candidates[:10], cap)
                deliveries[str(cap)] = dict(characters=len(encoded),
                    original_lines=[dict(path=p,line=n) for p,n in lines], response=json.loads(encoded) if encoded else None)
            save(args.output/'rankings'/method/(question['id']+'.json'), dict(
                id=question['id'], query=question['question'], method=method,
                candidates=candidates, deliveries=deliveries, native_packet=packet,
                stats=stats, seconds=time.monotonic()-started))
        print(json.dumps(dict(method=method, questions=len(questions), status='complete')),flush=True)
    save(args.output/'completion.json',dict(complete=True, questions=len(questions),methods=list(backends), model_calls=0))


def covered(spans, required):
    intervals = sorted((s['start'], s['end']) for s in spans if s['path'] == required['path'])
    cursor = required['line_start']
    for start,end in intervals:
        if start > cursor:
            break
        cursor = max(cursor, end+1)
        if cursor > required['line_end']:
            return True
    return False


def evaluate(args):
    protocol = read(args.input/'protocol.json')
    completion = read(args.input/'completion.json')
    if not completion['complete']:
        raise ValueError('Incomplete production outputs')
    split = read(args.dataset/'split.json')
    annotations = {r['id']:r for r in read(args.dataset/'scoring/annotations.json')}
    evidence = read(args.dataset/'scoring/evidence.json')
    selected = {r['id'] for r in read(Path(next(p for p in protocol['input_sha256'] if Path(p).name == 'dev-questions.json')))}
    if selected != set(split['ids']['dev']):
        raise ValueError('This optimization probe must contain the full existing development split only')
    rows, summaries = [], {}
    for method in completion['methods']:
        method_rows = []
        for qid in sorted(selected):
            record = read(args.input/'rankings'/method/(qid+'.json'))
            gold = [evidence[eid] for eid in annotations[qid]['required_evidence_ids']]
            metrics = {}
            for k in [1,3,5,10]:
                flags = [covered(record['candidates'][:k], span) for span in gold]
                metrics['recall@'+str(k)] = sum(flags)/len(flags)
                metrics['complete@'+str(k)] = int(all(flags))
            first = next((k for k in range(1,len(record['candidates'])+1)
                if any(covered(record['candidates'][:k],span) for span in gold)),None)
            metrics['mrr'] = 1/first if first else 0
            for cap,delivery in record['deliveries'].items():
                spans = [dict(path=r['path'],start=r['line'],end=r['line']) for r in delivery['original_lines']]
                flags = [covered(spans, span) for span in gold]
                metrics['delivered_recall_'+cap] = sum(flags)/len(flags)
                metrics['delivered_complete_'+cap] = int(all(flags))
            row = dict(id=qid, group=annotations[qid]['split_group'],method=method,metrics=metrics,
                production_output_sha256=sha(args.input/'rankings'/method/(qid+'.json')))
            rows.append(row); method_rows.append(row)
        summaries[method] = {}
        for key in method_rows[0]['metrics']:
            groups = defaultdict(list)
            for row in method_rows:
                groups[row['group']].append(row['metrics'][key])
            summaries[method][key] = dict(question_micro=sum(r['metrics'][key] for r in method_rows)/len(method_rows),
                group_macro=sum(sum(v)/len(v) for v in groups.values())/len(groups),groups=len(groups))
    save(args.output,dict(schema='development_retrieval_comparison_v2',formal_result=False,
        questions=len(selected), models_called=0, split='existing_development_only',
        production_protocol_sha256=sha(args.input/'protocol.json'),
        dataset_input_sha256={str(p):sha(p) for p in [args.dataset/'split.json',args.dataset/'scoring/annotations.json',args.dataset/'scoring/evidence.json']},
        summaries=summaries, rows=rows,
        limitations=['Post-hoc development diagnosis; no confirmatory test claims.',
            'Necessary evidence gold is not an exhaustive relevance pool; no precision claim.',
            'Span coverage requires every original line; compact excerpts can contain the main fact yet miss the full gold span.',
            'Question-micro and equal-group macro are both shown, never substituted silently.']))
    print(json.dumps(summaries),flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command',required=True)
    production = sub.add_parser('retrieve')
    for name in ('questions','corpus','manifest','source-map','graph','graph-v2','output'):
        production.add_argument('--'+name,type=Path,required=True)
    production.add_argument('--methods',nargs='+',choices=['graph_v1','typed_whole','typed_compact','typed_hierarchy_compact','bm25_current'],
        default=['graph_v1','typed_whole','typed_compact','typed_hierarchy_compact','bm25_current'])
    scoring = sub.add_parser('evaluate')
    for name in ('input','dataset','output'):
        scoring.add_argument('--'+name,type=Path,required=True)
    args = parser.parse_args()
    (retrieve if args.command == 'retrieve' else evaluate)(args)


if __name__ == '__main__':
    main()
