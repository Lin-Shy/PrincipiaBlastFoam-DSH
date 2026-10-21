"""Public-only retrieval runs; separate, hash-bound full-bank evaluation."""
import argparse
import ast
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import statistics
import sys
import time

PROJECT = Path(__file__).resolve().parents[2]
WORKSPACE = PROJECT.parent
sys.path.insert(0, str(PROJECT / 'src'))
RESOURCES = WORKSPACE / 'graduation-experiment-results/chapter2_retrieval/resources'
DATASET = WORKSPACE / 'graduation-datasets/chapter02_knowledge_qa/formal_v2_200'

def read(p): return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p, v):
    p = Path(p); p.parent.mkdir(parents=True, exist_ok=True)
    with p.open('x', encoding='utf-8') as f:
        json.dump(v, f, ensure_ascii=False, indent=2)

def snapshot(output):
    """Freeze the local import closure, including imports inside functions."""
    folder = Path(__file__).parent
    pending = [Path(__file__), folder / 'chapter2_knowledge_graph_v6.py', folder / 'chapter2_knowledge_graph_v5.py',
               folder / 'chapter2_knowledge_graph_v4.py', folder / 'chapter2_qa_backends.py',
               folder / 'chapter2_knowledge_input_guard.py', folder / 'chapter2_baseline_native.py',
               folder / 'canonical_evidence_v1.py']
    seen = {}
    while pending:
        p = pending.pop()
        if not p.exists() or p in seen: continue
        seen[p] = sha(p)
        for node in ast.walk(ast.parse(p.read_text(encoding='utf-8-sig'))):
            names = ([node.module] if isinstance(node, ast.ImportFrom) and node.module else
                     [v.name for v in node.names] if isinstance(node, ast.Import) else [])
            for name in names:
                local = folder / (name.split('.')[0] + '.py')
                core = PROJECT / 'src' / (name.replace('.', '/') + '.py')
                if local.exists(): pending.append(local)
                if core.exists(): pending.append(core)
    for p in (PROJECT / 'src/principia_core/retrieval').glob('knowledge*.py'):
        seen[p] = sha(p)
    for p, digest in seen.items():
        target = output / 'runtime' / p.relative_to(PROJECT)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('xb') as f: f.write(p.read_bytes())
    return {p.relative_to(PROJECT).as_posix(): digest for p, digest in seen.items()}

def engine(method, graph):
    from chapter2_qa_backends import NativeBackend
    common = dict(corpus=RESOURCES/'corpus', corpus_manifest=RESOURCES/'source-map.json')
    if method in {'e5','hybrid'}:
        from chapter2_qa_backends import create_backend
        return create_backend(method, common['corpus'], common['corpus_manifest'], e5_index=RESOURCES/'e5')
    if method == 'bm25':
        from chapter2_baseline_native import NoGraphBM25
        return NativeBackend(NoGraphBM25(common['corpus'], common['corpus_manifest']))
    if method.startswith('v6_'):
        from chapter2_knowledge_graph_v6 import BilingualScopeGraph
        policy=method.removeprefix('v6_').split('_no_')[0]
        options={'with_cross':False} if method.endswith('_no_cross') else {'with_conditions':False} if method.endswith('_no_conditions') else {}
        return NativeBackend(BilingualScopeGraph(graph, **common, semantic_policy=policy, options=options), graph=True)
    if method.startswith('v5_'):
        from chapter2_knowledge_graph_v5 import FocusedEvidenceGraph
        return NativeBackend(FocusedEvidenceGraph(graph, **common, policy=method.removeprefix('v5_')), graph=True)
    from chapter2_knowledge_graph_v4 import AdaptiveSourceGraph
    policy = {'v4_full': 'adaptive', 'v4_no_context': 'none', 'v4_adjacent': 'adjacent',
              'v4_blanket': 'blanket', 'v4_no_extension': 'none'}[method]
    options = dict(with_paths=False) if method == 'v4_no_extension' else {}
    # The variant field verifies physical ablation artifacts. For no-extension,
    # use its independently persisted variant rather than relabeling full.
    if method == 'v4_no_extension': graph = RESOURCES/'graphs/no_extension.json'
    return NativeBackend(AdaptiveSourceGraph(graph, **common, context_policy=policy,
        options=options), graph=True)

def retrieve(a):
    questions = DATASET/'model/questions.json'
    from chapter2_knowledge_input_guard import install
    guard = install(questions)
    from principia_core.retrieval.knowledge_qa import FrozenKnowledgeCorpus, KnowledgeToolSession, KnowledgeBudget
    qs = read(questions)
    if len(qs) != 200 or any(set(q) != {'id', 'question'} for q in qs):
        raise ValueError('Exact public 200-question bank required')
    output = a.output.resolve()
    if output.exists(): raise FileExistsError('New immutable run directory required')
    bindings = snapshot(output)
    graph = a.graph.resolve() if a.graph else RESOURCES/'graphs/full.json'
    if a.method == 'v4_no_extension': graph = RESOURCES/'graphs/no_extension.json'
    protocol = dict(schema='optimization_200_public_retrieval_v1', formal_result=False,
        method=a.method, run_id=output.name, questions_sha256=sha(questions), question_ids=[q['id'] for q in qs],
        graph_sha256=sha(graph), graph=str(graph), source_map_sha256=sha(RESOURCES/'source-map.json'),
        corpus_manifest_sha256=sha(RESOURCES/'corpus-manifest.json'), implementation_sha256=bindings,
        query_policy='Identical unmodified public question; no gold, translation, tuned query list or model planning',
        ranking_limit=64, delivery_blocks=10, budgets=[6000,12000,24000],
        model_calls=0, input_guard=guard, design_sha256=sha(WORKSPACE/'graduation-thesis-materials/graduation-research/chapters/chapter02.md'))
    if a.method in {'e5','hybrid'}:
        protocol['e5_index_binding'] = {name:sha(RESOURCES/'e5'/name) for name in ['manifest.json','passages.json','embeddings.npy']}
    save(output/'protocol.json', protocol)
    backend = engine(a.method, graph)
    corpus = FrozenKnowledgeCorpus(RESOURCES/'corpus', RESOURCES/'corpus-manifest.json')
    all_started = time.monotonic()
    for index, q in enumerate(qs, 1):
        started = time.monotonic(); packet, stats = backend.ranked(q['question'], 64)
        seconds = time.monotonic()-started
        candidates = []
        for row in packet['items']:
            if row.get('mapping_status') == 'unmappable':
                raise ValueError('Current graph/BM25 corpus contains an unmappable native result')
            for span in row['ranges']:
                candidates.append(dict(path=row['path'], start=span['start'], end=span['end'],
                    source_sha256=corpus.hashes[row['path']], native_unit=row.get('native_unit'),
                    native_rank=row['native_rank'], scope_id=row.get('owner')))
        # Exact same source delivery and envelope budget for every backend.
        # Deduplicate range identities without dropping non-gold results.
        unique = []; seen = set()
        for row in candidates:
            key = row['path'], row['start'], row['end']
            if key not in seen: unique.append(row); seen.add(key)
        deliveries = {}
        for cap in protocol['budgets']:
            actual=unique
            budget_packet=None
            if a.method=='v5_adaptive' or a.method.startswith('v6_'):
                budget_packet=backend.engine.read_for_budget(packet['native_ranking'],cap)
                actual=[];budget_seen=set()
                for row in budget_packet['items']:
                    for span in row['ranges']:
                        key=row['path'],span['start'],span['end']
                        if key in budget_seen:continue
                        budget_seen.add(key)
                        actual.append(dict(path=row['path'],start=span['start'],end=span['end']))
            tools = KnowledgeToolSession('graph' if a.method != 'bm25' else 'bm25', corpus, backend,
                KnowledgeBudget(tool_calls=1, tool_characters=cap, total_characters=cap))
            encoded, lines = tools._deliver(actual[:10], cap)
            deliveries[str(cap)] = dict(characters=len(encoded), original_lines=[dict(path=p,line=n) for p,n in lines],
                response=json.loads(encoded) if encoded else None,
                budget_context_characters=min(2400,max(1200,cap//5)) if a.method=='v5_adaptive' or a.method.startswith('v6_') else None,
                budget_read_plan=[dict(path=r['path'],ranges=r['ranges']) for r in budget_packet['items']] if budget_packet else None)
        # Verbose graph diagnostics are recorded once in the native packet;
        # the evaluator reads only candidates and actual delivered line IDs.
        save(output/'rankings'/(q['id']+'.json'), dict(id=q['id'], query=q['question'], method=a.method,
            candidates=unique, deliveries=deliveries, native_packet=packet, seconds=seconds))
        if index % 25 == 0:
            print(json.dumps(dict(method=a.method, completed=index, total=200,
                elapsed_seconds=round(time.monotonic()-all_started,2))), flush=True)
    save(output/'completion.json', dict(complete=True, questions=200, model_calls=0,
        elapsed_seconds=time.monotonic()-all_started, protocol_sha256=sha(output/'protocol.json'),
        output_sha256={q['id']:sha(output/'rankings'/(q['id']+'.json')) for q in qs}))

def evaluate(a):
    from canonical_evidence_v1 import canonical_unit, score, score_identifier_layer
    from chapter2_v2_retrieval_probe import covered
    protocol = read(a.input/'protocol.json'); completion = read(a.input/'completion.json')
    if not completion['complete'] or completion['protocol_sha256'] != sha(a.input/'protocol.json'):
        raise ValueError('Complete bound retrieval required')
    binding = read(DATASET/'binding.json'); annotations = {q['id']:q for q in read(DATASET/'scoring/annotations.json')}
    evidence = read(DATASET/'scoring/evidence.json')
    if set(protocol['question_ids']) != set(annotations): raise ValueError('Full 200-question scope required')
    rows = []
    for qid in protocol['question_ids']:
        p = a.input/'rankings'/(qid+'.json')
        if sha(p) != completion['output_sha256'][qid]: raise ValueError('Retrieval output drift')
        r = read(p); ann = annotations[qid]
        gold = [dict(id=eid, path=evidence[eid]['path'], start=evidence[eid]['line_start'],
            end=evidence[eid]['line_end'], sha256=evidence[eid]['file_sha256']) for eid in ann['required_evidence_ids']]
        units = []; chars = 0
        for n, item in enumerate(r['candidates'],1):
            chars += item['end']-item['start']+1
            units.append(canonical_unit(path=item['path'], start=item['start'], end=item['end'],
                source_sha256=item['source_sha256'], source_kind='manual' if item['path'].startswith('manual/') else 'tutorial',
                native_unit=item['native_unit'] or str(n), native_rank=item['native_rank'], query_step=0,
                source_characters=0, cumulative_returned_characters=0,
                cumulative_query_seconds=r['seconds'], scope_id=item['scope_id']))
        raw = score(gold, units); m = {'mrr': raw['mrr']}
        for k in (1,3,5,10):
            for source,target in [('recall','recall'),('complete_evidence_set_success','complete')]:
                m[target+'@'+str(k)] = raw['top_k'][str(k)][source]
        m['file_ndcg@10'] = score_identifier_layer([g['path'] for g in gold],
            [x['path'] for x in r['candidates']])['top_k']['10']['ndcg']
        for cap, delivery in r['deliveries'].items():
            spans = [dict(path=v['path'],start=v['line'],end=v['line']) for v in delivery['original_lines']]
            flags = [covered(spans,dict(path=g['path'],line_start=g['start'],line_end=g['end'])) for g in gold]
            m['delivered_recall_'+cap] = sum(flags)/len(flags)
            m['delivered_complete_'+cap] = int(all(flags))
            m['delivered_characters_'+cap] = delivery['characters']
        kind = ('M' if ann['labels']['evidence_integration']=='multiple' else 'S')+str(int(ann['labels']['condition_discrimination']))
        rows.append(dict(id=qid, group=ann['split_group'], type=kind, metrics=m, seconds=r['seconds']))
    def aggregate(selected):
        group = defaultdict(list)
        for row in selected: group[row['group']].append(row)
        return dict(questions=len(selected), groups=len(group),
            micro={k:statistics.mean(r['metrics'][k] for r in selected) for k in selected[0]['metrics']},
            group_macro={k:statistics.mean(statistics.mean(r['metrics'][k] for r in rs) for rs in group.values()) for k in selected[0]['metrics']},
            latency_seconds=dict(mean=statistics.mean(r['seconds'] for r in selected),
                median=statistics.median(r['seconds'] for r in selected)))
    result = dict(schema='optimization_200_retrieval_analysis_v1', formal_result=False,
        method=protocol['method'], run_id=protocol.get('run_id',a.input.name), dataset_sha256=binding['dataset_sha256'],
        protocol_sha256=sha(a.input/'protocol.json'), completion_sha256=sha(a.input/'completion.json'),
        gold_sha256={n:sha(DATASET/n) for n in ['scoring/annotations.json','scoring/evidence.json']},
        summary=aggregate(rows), by_type={t:aggregate([r for r in rows if r['type']==t]) for t in ['S0','S1','M0','M1']}, rows=rows,
        limits=['Full-bank adaptive development, not independent unseen validation or final QA results.',
            'Canonical original-range ranks retain non-gold results; gold is a necessary, non-exhaustive evidence pool.',
            'nDCG is reported only on deduplicated canonical files; repeated overlapping source ranges cannot create repeated relevant-document gains.',
            'Actual delivered recall includes JSON/line envelope overhead under the same character budget.'])
    save(a.output, result)
    print(json.dumps(dict(method=protocol['method'], micro={k:round(v,5) for k,v in result['summary']['micro'].items()
        if k in {'recall@10','complete@10','delivered_recall_6000','delivered_complete_6000','delivered_complete_24000'}})), flush=True)

def main():
    p = argparse.ArgumentParser(description=__doc__); sub = p.add_subparsers(dest='command',required=True)
    r = sub.add_parser('retrieve'); r.add_argument('--method', required=True)
    r.add_argument('--output',type=Path,required=True); r.add_argument('--graph',type=Path)
    e = sub.add_parser('evaluate'); e.add_argument('--input',type=Path,required=True); e.add_argument('--output',type=Path,required=True)
    a = p.parse_args(); (retrieve if a.command=='retrieve' else evaluate)(a)
if __name__=='__main__': main()
