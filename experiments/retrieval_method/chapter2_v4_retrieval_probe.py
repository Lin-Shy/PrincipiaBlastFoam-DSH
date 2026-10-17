"""Public-query retrieval, actual source delivery and separate Gold-only analysis."""
import argparse
from collections import defaultdict
import json
import os
from pathlib import Path
import sys
import time

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT / 'src'))
from chapter2_v2_retrieval_probe import read, save, sha, covered
from chapter2_knowledge_backends_v4 import METHODS


def source_candidates(packet, hashes):
    candidates = []
    for row in packet['items']:
        if row.get('mapping_status') == 'unmappable':
            candidates.append(dict(path=row.get('path'), start=None, end=None, mapping_status='unmappable',
                native_unit=row.get('native_unit'), native_rank=row.get('native_rank')))
            continue
        for span in row['ranges']:
            candidates.append(dict(path=row['path'], start=span['start'], end=span['end'],
                source_sha256=hashes[row['path']], source_kind='manual' if row['path'].startswith('manual/') else 'tutorial',
                native_unit=row['native_unit'], native_rank=row['native_rank'], scope_id=row.get('owner'), mapping_status='mapped'))
    return candidates


def mapped(spans):
    return [s for s in spans if s.get('mapping_status') != 'unmappable']


def retrieval_metrics(record, gold):
    from canonical_evidence_v1 import score_identifier_layer
    candidates = record['candidates']; metrics = {}
    for k in (1, 3, 5, 10):
        flags = [covered(mapped(candidates[:k]), atom) for atom in gold]
        metrics['recall@' + str(k)] = sum(flags) / len(flags)
        metrics['complete@' + str(k)] = int(all(flags))
        metrics['hit@' + str(k)] = int(any(flags))
    first = next((k for k in range(1, len(candidates) + 1) if any(covered(mapped(candidates[:k]), atom) for atom in gold)), None)
    metrics['mrr'] = 1 / first if first else 0
    # A comparable, deduplicated FILE ranking, not repeated chunk gains.
    files = [s['path'] if s['mapping_status'] == 'mapped' else f'__unmapped_{i}' for i, s in enumerate(candidates)]
    file_score = score_identifier_layer(sorted({g['path'] for g in gold}), files)
    metrics['file_ndcg@10'] = file_score['top_k']['10']['ndcg']
    for cap, delivery in record['deliveries'].items():
        spans = [dict(path=r['path'], start=r['line'], end=r['line']) for r in delivery['original_lines']]
        flags = [covered(spans, atom) for atom in gold]
        metrics['delivered_recall_' + cap] = sum(flags) / len(flags)
        metrics['delivered_complete_' + cap] = int(all(flags))
    return metrics


def retrieve(args):
    from chapter2_knowledge_input_guard import install
    guard = install(args.questions)
    from chapter2_knowledge_backends_v4 import backend, tool_method
    from principia_core.retrieval.knowledge_qa import FrozenKnowledgeCorpus, KnowledgeToolSession, KnowledgeBudget
    if args.output.exists():raise FileExistsError('New immutable retrieval revision required')
    resources = read(args.resources); questions = read(args.questions)
    if any(set(q) != {'id', 'question'} for q in questions) or len({q['id'] for q in questions}) != len(questions):raise ValueError('Unique public questions only')
    corpus = FrozenKnowledgeCorpus(resources['corpus'], resources['corpus_manifest'])
    source_files = [Path(__file__), PROJECT / 'experiments/retrieval_method/chapter2_knowledge_graph_v4.py',
        PROJECT / 'experiments/retrieval_method/chapter2_knowledge_graph_v3.py', PROJECT / 'experiments/retrieval_method/chapter2_knowledge_graph_v2.py',
        PROJECT / 'experiments/retrieval_method/chapter2_knowledge_graph_retriever.py', PROJECT / 'experiments/retrieval_method/chapter2_knowledge_backends_v4.py',
        PROJECT / 'experiments/retrieval_method/chapter2_baseline_native.py', PROJECT / 'experiments/retrieval_method/chapter2_qa_backends.py',
        PROJECT / 'src/principia_core/retrieval/knowledge_qa.py']
    save(args.output / 'protocol.json', dict(schema='public_query_retrieval_v4', formal_result=False, question_ids=[q['id'] for q in questions],
        questions_sha256=sha(args.questions), resources_sha256=sha(args.resources), methods=args.methods, budgets=[6000, 12000, 24000],
        implementation_sha256={str(p.relative_to(PROJECT)): sha(p) for p in source_files},
        graph_artifacts={name: sha(Path(resources[name])) for name in ('graph_full', 'graph_no_cross', 'graph_no_conditions', 'graph_no_extension')},
        query_policy='Identical unmodified public natural questions; no model planning or Gold input.', input_guard=guard,
        context_characters=args.context_characters, parent_ratio=args.parent_ratio, model_calls=0,
        embedding_runtime_cache=os.environ.get('HF_HUB_CACHE'), e5_manifest_sha256=sha(Path(resources['e5_manifest'])),
        rank_scope='First returned authoritative source blocks; file_nDCG uses deduplicated canonical original files, not chunks.'))
    for method in args.methods:
        engine = backend(method, resources, context_characters=args.context_characters, parent_ratio=args.parent_ratio)
        for q in questions:
            started = time.monotonic()
            packet, stats = engine.ranked(q['question'], 64) if engine else (dict(items=[]), dict(no_external_knowledge=True))
            seconds = time.monotonic() - started
            candidates = source_candidates(packet, corpus.hashes); deliveries = {}
            for cap in (6000, 12000, 24000):
                if engine:
                    tools = KnowledgeToolSession(tool_method(method), corpus, engine, KnowledgeBudget(tool_calls=1, tool_characters=cap, total_characters=cap))
                    # The model-facing legacy adapter cannot return binary text;
                    # native ranking penalties remain in candidates above.
                    encoded, lines = tools._deliver(mapped(candidates)[:10], cap)
                else:encoded, lines = '{"evidence":[],"truncated":false}', []
                deliveries[str(cap)] = dict(characters=len(encoded), original_lines=[dict(path=p, line=n) for p, n in lines],
                    response=json.loads(encoded) if encoded else None)
            save(args.output / 'rankings' / method / (q['id'] + '.json'), dict(id=q['id'], query=q['question'], method=method,
                candidates=candidates, deliveries=deliveries, native_packet=packet, stats=stats, seconds=seconds))
        print(json.dumps(dict(method=method, completed=len(questions), model_calls=0)), flush=True)
    save(args.output / 'completion.json', dict(complete=True, questions=len(questions), methods=args.methods, model_calls=0))


def evaluate(args):
    protocol = read(args.input / 'protocol.json'); completion = read(args.input / 'completion.json')
    if not completion['complete']:raise ValueError('Complete production outputs required')
    split = read(args.dataset / 'split.json'); selected = set(protocol['question_ids'])
    if selected != set(split['ids'][args.split]):raise ValueError('Complete registered split required')
    annotations = {r['id']: r for r in read(args.dataset / 'scoring/annotations.json')}; evidence = read(args.dataset / 'scoring/evidence.json')
    rows = []; summaries = {}
    for method in completion['methods']:
        per_method = []
        for qid in protocol['question_ids']:
            path = args.input / 'rankings' / method / (qid + '.json'); record = read(path)
            gold = [evidence[eid] for eid in annotations[qid]['required_evidence_ids']]
            row = dict(id=qid, group=annotations[qid]['split_group'], method=method, metrics=retrieval_metrics(record, gold),
                seconds=record['seconds'], production_output_sha256=sha(path))
            per_method.append(row); rows.append(row)
        summaries[method] = {}
        for key in per_method[0]['metrics']:
            groups = defaultdict(list)
            for row in per_method:groups[row['group']].append(row['metrics'][key])
            summaries[method][key] = dict(question_micro=sum(r['metrics'][key] for r in per_method) / len(per_method),
                group_macro=sum(sum(v) / len(v) for v in groups.values()) / len(groups), groups=len(groups))
        print(method, {k: round(summaries[method][k]['group_macro'] * 100, 2) for k in ['recall@10', 'delivered_recall_6000', 'delivered_complete_6000', 'file_ndcg@10']}, flush=True)
    save(args.output, dict(schema='canonical_source_retrieval_comparison_v4', formal_result=False, split=args.split, questions=len(selected),
        production_protocol_sha256=sha(args.input / 'protocol.json'), summaries=summaries, rows=rows,
        gold_sha256={p: sha(args.dataset / p) for p in ['split.json', 'scoring/annotations.json', 'scoring/evidence.json']},
        limits=['Repeated development tuning if split=dev; test outcomes cannot select this frozen method.',
            'Gold is necessary evidence, not an exhaustive relevance pool. No ordinary precision claim.',
            'file_nDCG@10 is explicitly on canonical files; source-span coverage and exact actual character delivery are separate.']))


def main():
    p = argparse.ArgumentParser(description=__doc__); sub = p.add_subparsers(dest='command', required=True)
    r = sub.add_parser('retrieve')
    for name in ('resources', 'questions', 'output'):r.add_argument('--' + name, type=Path, required=True)
    r.add_argument('--methods', nargs='+', choices=METHODS, default=['bm25', 'e5', 'hybrid', 'graph', 'no_context', 'adjacent_only', 'parent_blanket'])
    r.add_argument('--context-characters', type=int, default=2400); r.add_argument('--parent-ratio', type=float, default=.5)
    e = sub.add_parser('evaluate')
    for name in ('input', 'dataset', 'output'):e.add_argument('--' + name, type=Path, required=True)
    e.add_argument('--split', choices=['dev', 'test'], required=True)
    a = p.parse_args(); (retrieve if a.command == 'retrieve' else evaluate)(a)


if __name__ == '__main__':main()
