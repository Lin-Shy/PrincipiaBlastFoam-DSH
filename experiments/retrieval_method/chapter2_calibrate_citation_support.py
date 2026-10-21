"""Prepare and run a fixed, source-reviewed auxiliary citation calibration.

Prepare first without credentials; execution is from its immutable runtime.
Existing source-reviewed candidate texts are reused byte-for-byte, not authored
by the online judge. Expected labels are never in the judge request.
"""
import argparse
from collections import Counter
from pathlib import Path
from chapter2_autonomous_qa import PROJECT, RecordedQwenClient, load_tokenizer, read, save, sha
from chapter2_qwen_proxy_config import settings
from chapter2_citation_support import PROMPT, MODEL, score_citations
from principia_core.retrieval.knowledge_qa import FrozenKnowledgeCorpus

QUESTION_IDS = ('P01-04', 'P04-03', 'P06-05', 'E28-02')
SOURCE_FILES = ('experiments/retrieval_method/chapter2_calibrate_citation_support.py',
    'experiments/retrieval_method/chapter2_citation_support.py',
    'experiments/retrieval_method/chapter2_autonomous_qa.py',
    'experiments/retrieval_method/chapter2_qwen_proxy_config.py',
    'src/principia_core/__init__.py', 'src/principia_core/retrieval/__init__.py',
    'src/principia_core/retrieval/knowledge_agent.py', 'src/principia_core/retrieval/knowledge_qa.py')
REVIEW = {
 'P01-04': '已读11_amr.md 62–75：fieldValue的x限定为已存储标量；不支持直接向量U，不能由该段省略标量转换/存储条件。',
 'P04-03': '已读16_utilities.md 225–229及atmosphereProperties 28–43：查表后可静水校正；correct控制后续步骤，不保证校正后仍处处等于原表。',
 'P06-05': '已读DDT combustionProperties 18–28：RaviPetersen、unstrained与Su数值独立条目；只修改数值不修改另两个条目。',
 'E28-02': '已读workshop 0/p.orig 17–46与07_burst_patches.md 1–12：实例intactPatch/zeroGradient、手册intactField；如实比较差异正确，不能混淆通用与实例角色。'}


def prepare(args):
    if args.output.exists(): raise FileExistsError('new immutable calibration revision required')
    seal_path = args.dataset / 'dataset-seal.json'; seal = read(seal_path)
    for relative, expected in seal['files'].items():
        target = (args.dataset / relative).resolve()
        if not target.is_relative_to(args.dataset.resolve()) or sha(target) != expected:
            raise ValueError('dataset seal drift')
    annotations = {q['id']: q for q in read(args.dataset / 'scoring/annotations.json')}
    evidence = read(args.dataset / 'scoring/evidence.json')
    corpus = FrozenKnowledgeCorpus(args.corpus, args.manifest)
    bases = {}; source_bindings = {}
    for qid in QUESTION_IDS:
        if annotations[qid]['split'] != 'dev': raise ValueError('citation calibration must only use development questions')
        variants = {}
        for kind in ('positive', 'contradiction'):
            path = args.controls / 'generation/sessions' / (qid + '_' + kind) / 'result.json'
            row = read(path)
            if row['question']['id'] != qid or row['status'] != 'answered': raise ValueError('invalid reviewed control')
            variants[kind] = row; source_bindings[str(path.resolve())] = sha(path)
        refs = []
        for eid in annotations[qid]['required_evidence_ids']:
            e = evidence[eid]; raw = corpus.read(e['path'], e['line_start'], e['line_end'])
            if raw['sha256'] != e['file_sha256'] or '\n'.join(r['text'] for r in raw['lines']) != e['excerpt']:
                raise ValueError('reviewed original span drift')
            refs.append({'path': e['path'], 'start': e['line_start'], 'end': e['line_end']})
        bases[qid] = (variants, refs)
    groups = {annotations[q]['split_group'] for q in QUESTION_IDS}
    if len(groups) < 4: raise ValueError('citation controls require four distinct knowledge groups')
    cases = []; expected = []
    for i, qid in enumerate(QUESTION_IDS):
        variants, refs = bases[qid]; unrelated = bases[QUESTION_IDS[(i + 1) % len(QUESTION_IDS)]][1]
        for kind in ('full', 'unrelated', 'extra_unused', 'contradiction', 'no_citations', 'undelivered'):
            candidate = variants['contradiction' if kind == 'contradiction' else 'positive']
            selected_refs = [] if kind == 'no_citations' else unrelated if kind == 'unrelated' else refs + unrelated if kind == 'extra_unused' else refs
            lines = [] if kind == 'undelivered' else [{'path': r['path'], 'line': n}
                for r in selected_refs for n in range(r['start'], r['end'] + 1)]
            cid = qid + '_' + kind
            cases.append({'id': cid, 'question_id': qid, 'question': candidate['question']['question'],
                'result': {'status': 'answered', 'answer': candidate['answer'], 'references': selected_refs,
                    'tool_events': [{'delivered_original_lines': lines}]}})
            expected.append({'id': cid, 'question_id': qid, 'split_group': annotations[qid]['split_group'],
                'type': kind, 'expected_complete_citation_support': int(kind == 'full'),
                'reason': REVIEW[qid] + '完整引用为1；跨组无关/额外无关引用、明确矛盾、无引用或未交付引用为0。'})
    save(args.output / 'cases.json', cases)
    save(args.output / 'expected.json', {'schema': 'source_reviewed_citation_controls_v1', 'reviewer': 'Codex (AI)',
        'human_truth': False, 'review_before_online_judge': True, 'controls': expected, 'source_control_sha256': source_bindings})
    sources = {}
    for relative in SOURCE_FILES:
        original = PROJECT / relative; target = args.output / 'runtime' / relative
        target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(original.read_bytes()); sources[relative] = sha(original)
    _, tokenizer = load_tokenizer(args.tokenizer, MODEL)
    save(args.output / 'protocol.json', {'schema': 'citation_union_support_calibration_v1', 'formal_result': False,
        'purpose': 'auxiliary_measurement_reliability_not_answer_accuracy', 'judge_model': MODEL, 'judge_prompt': PROMPT,
        'temperature': 0, 'enable_thinking': False, 'max_tokens': 4096, 'input_token_limit': 32768,
        'transport_attempts_max': 3, 'content_retries': 0, 'runtime_source_sha256': sources,
        'dataset_seal_sha256': sha(seal_path), 'cases_sha256': sha(args.output / 'cases.json'),
        'expected_sha256': sha(args.output / 'expected.json'), 'corpus_manifest_sha256': sha(args.manifest),
        'tokenizer': tokenizer, 'resources': {'corpus': str(args.corpus.resolve()), 'manifest': str(args.manifest.resolve()),
            'tokenizer': str(args.tokenizer.resolve())}, 'acceptance': {
                'minimum_planned_controls': 24, 'minimum_question_groups': 4,
                'judge_parse_rate_minimum': .9, 'complete_agreement_all_planned_minimum': .9,
                'complete_agreement_each_class_minimum': .8,
                'unknown_and_unattempted_count_as_disagreement': True},
        'limits': 'AI source-reviewed controls are fallible. Answer-wide citation union, not inline attribution or physical truth. Primary v7 unchanged.'})
    print({'status': 'prepared', 'cases': len(cases), 'groups': len(groups), 'model_requests': 0}, flush=True)


def execute(args):
    root = args.prepared; protocol = read(root / 'protocol.json')
    if protocol['schema'] != 'citation_union_support_calibration_v1' or protocol['judge_prompt'] != PROMPT:
        raise ValueError('citation protocol/prompt drift')
    for relative, expected in protocol['runtime_source_sha256'].items():
        if sha(PROJECT / relative) != expected: raise ValueError('citation frozen runtime drift')
    import importlib
    for name, relative in {'principia_core': 'src/principia_core/__init__.py',
            'principia_core.retrieval.knowledge_qa': 'src/principia_core/retrieval/knowledge_qa.py'}.items():
        if Path(importlib.import_module(name).__file__).resolve() != (PROJECT / relative).resolve():
            raise ValueError('citation imported core outside frozen runtime')
    if sha(root / 'cases.json') != protocol['cases_sha256'] or sha(root / 'expected.json') != protocol['expected_sha256']:
        raise ValueError('citation calibration controls drift')
    resources = protocol['resources']; corpus = FrozenKnowledgeCorpus(Path(resources['corpus']), Path(resources['manifest']))
    if corpus.manifest_sha256 != protocol['corpus_manifest_sha256']: raise ValueError('citation corpus drift')
    counter, tokenizer = load_tokenizer(Path(resources['tokenizer']), MODEL)
    if tokenizer != protocol['tokenizer']: raise ValueError('citation tokenizer drift')
    base, key = settings(args.proxy_settings); endpoint = base + '/chat/completions'
    admission = {'protocol_sha256': sha(root / 'protocol.json'), 'endpoint': endpoint, 'judge_model': MODEL}
    admission_path = root / 'execution.json'
    if admission_path.exists() and read(admission_path) != admission: raise ValueError('citation execution binding drift')
    save(admission_path, admission); rows = {}; circuit = False
    for case in read(root / 'cases.json'):
        folder = root / 'sessions' / case['id']; path = folder / 'score.json'
        if path.exists():
            score = read(path)
            if score['protocol_sha256'] != admission['protocol_sha256']: raise ValueError('citation score protocol drift')
            if read(folder / 'score-binding.json') != {'score_sha256': sha(path), 'execution_sha256': sha(admission_path)}:
                raise ValueError('citation persisted score drift')
        else:
            score = {'protocol_sha256': admission['protocol_sha256'], **score_citations(case['question'], case['result'], corpus,
                RecordedQwenClient(endpoint, key, folder / 'requests'), counter)}
            save(path, score); save(folder / 'score-binding.json', {'score_sha256': sha(path), 'execution_sha256': sha(admission_path)})
        rows[case['id']] = score
        print({'id': case['id'], 'status': score['status'], 'complete': score['metrics']['complete_citation_support']}, flush=True)
        if score.get('reason') in {'transport_error', 'http_rejected'}: circuit = True; break
    controls = read(root / 'expected.json')['controls']; by_class = {}; agreement = 0; judge_planned = judge_parsed = 0
    for c in controls:
        score = rows.get(c['id']); known = score['metrics']['complete_citation_support'] if score else None
        good = known is not None and known == c['expected_complete_citation_support']; agreement += good
        counts = by_class.setdefault(c['type'], {'planned': 0, 'agreement': 0}); counts['planned'] += 1; counts['agreement'] += good
        if c['type'] not in {'no_citations', 'undelivered'}:
            judge_planned += 1; judge_parsed += bool(score and score['status'] == 'citation_judged')
    for counts in by_class.values(): counts['rate'] = counts['agreement'] / counts['planned']
    limits = protocol['acceptance']; parse_rate = judge_parsed / judge_planned; agree_rate = agreement / len(controls)
    accepted = (len(controls) >= limits['minimum_planned_controls'] and len({c['split_group'] for c in controls}) >= limits['minimum_question_groups']
        and parse_rate >= limits['judge_parse_rate_minimum'] and agree_rate >= limits['complete_agreement_all_planned_minimum']
        and all(c['rate'] >= limits['complete_agreement_each_class_minimum'] for c in by_class.values()))
    save(root / 'report.json', {'schema': 'citation_support_calibration_report_v1', 'formal_result': False,
        'accepted': accepted, 'human_truth': False, 'primary_v7_unchanged': True, 'protocol_sha256': admission['protocol_sha256'],
        'planned_controls': len(controls), 'completed_controls': len(rows), 'judge_planned': judge_planned,
        'judge_parsed': judge_parsed, 'judge_parse_rate': parse_rate, 'complete_agreement': agreement,
        'complete_agreement_rate': agree_rate, 'per_class': by_class, 'transport_circuit_open': circuit,
        'unknown_and_unattempted_not_excluded': True,
        'score_sha256': {cid: sha(root / 'sessions' / cid / 'score.json') for cid in rows}})


def main():
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('--prepared', type=Path); p.add_argument('--proxy-settings', type=Path)
    for name in ('dataset', 'controls', 'corpus', 'manifest', 'tokenizer', 'output'): p.add_argument('--' + name, type=Path)
    a = p.parse_args()
    if a.prepared:
        if not a.proxy_settings: p.error('--proxy-settings required for execution')
        execute(a)
    else:
        if any(getattr(a, name) is None for name in ('dataset', 'controls', 'corpus', 'manifest', 'tokenizer', 'output')):
            p.error('all preparation inputs required')
        prepare(a)


if __name__ == '__main__': main()
