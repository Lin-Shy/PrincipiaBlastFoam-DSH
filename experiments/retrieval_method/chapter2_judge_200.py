"""New-bank, seven-control proxy judge calibration; score-side data only."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import sys

from chapter2_optimization_200 import PROJECT, RESOURCES, DATASET, read, save, sha, snapshot
sys.path.insert(0, str(PROJECT/'src'))
from principia_core.retrieval.knowledge_qa import FrozenKnowledgeCorpus
from chapter2_answer_scoring import scoring_payload
from chapter2_judge_200_rubric import requests as source_free_requests, parse as parse_partial_judgments
from chapter2_qwen_routing import routed_client


def freeze(output):
    bindings = snapshot(output)
    names = ['chapter2_judge_200.py', 'chapter2_judge_200_rubric.py', 'chapter2_answer_scoring.py', 'chapter2_source_free_answer_scoring.py',
        'chapter2_reasoning_answer_scoring.py', 'chapter2_partial_answer_scoring.py', 'chapter2_segment_answer_scoring.py',
        'chapter2_qwen_routing.py', 'chapter2_qwen_proxy_config.py', 'chapter2_qwen_local.py']
    for name in names:
        source = Path(__file__).with_name(name)
        rel = source.relative_to(PROJECT).as_posix(); bindings[rel] = sha(source)
        target = output/'runtime'/rel
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(source.read_bytes())
    return bindings


def call_once(client, body, turn):
    path = client.folder/f'{turn:02d}.json'
    if path.exists():
        record = read(path)
        if record['request'] != body or record['status'] == 'in_flight':
            raise ValueError('Unresolved or changed judge request cannot be replayed')
        return record
    return client(body, turn)


def judged(payload, folder):
    client = routed_client('qwen3-14b', folder/'requests', workload='bulk', timeout=180)
    requests = source_free_requests(payload)
    records = [call_once(client, r['body'], i) for i, r in enumerate(requests)]
    return parse_partial_judgments(records, payload)


def prepare(a):
    if a.output.exists(): raise FileExistsError('New calibration directory required')
    qs = {q['id']:q['question'] for q in read(DATASET/'model/questions.json')}
    anns = {r['id']:r for r in read(DATASET/'scoring/annotations.json')}
    evidence = read(DATASET/'scoring/evidence.json')
    corpus = FrozenKnowledgeCorpus(RESOURCES/'corpus', RESOURCES/'corpus-manifest.json')
    def complete(qid): return '\n'.join(p['claim'] for p in anns[qid]['required_points'])
    controls = [
        ('C01', 'P01-01', complete('P01-01'), dict(complete_lower=1, complete_upper=1)),
        ('C02', 'P01-01', '不知道，没有足够信息回答。', dict(complete_lower=0, complete_upper=0, required_point_coverage_upper=0)),
        ('C03', 'P01-01', anns['P01-01']['required_points'][0]['claim'], dict(complete_lower=0, complete_upper=0)),
        ('C04', 'P01-01', 'fieldValue表示压力相对于精确解的相对误差，不是压力场本身。', dict(complete_lower=0, complete_upper=0)),
        ('C05', 'P01-02', complete('P01-02'), dict(complete_lower=1, complete_upper=1, applicability='pass')),
        ('C06', 'P01-02', 'fieldValue取压力值，所以仍然很大。delta也一定很大，因为相邻单元的压力都很高。', dict(complete_lower=0, complete_upper=0, applicability='fail')),
        ('C07', 'P01-01', complete('P01-01')+'\n我已经运行这个仿真并确认没有任何数值误差。', dict(complete_lower=0)),
    ]
    bindings = freeze(a.output)
    cases = []
    for cid, qid, answer, expected in controls:
        payload = scoring_payload(qs[qid], anns[qid], evidence, corpus, answer)
        save(a.output/'payloads'/(cid+'.json'), payload)
        cases.append(dict(id=cid, question_id=qid, expected=expected,
            partial_coverage_required=cid=='C03',
            payload_sha256=sha(a.output/'payloads'/(cid+'.json')), requests=len(source_free_requests(payload))))
    protocol = dict(schema='new_200_bank_judge_calibration_v2', formal_qa_result=False,
        model='qwen3-14b', provider='qwen_proxy', workload='bulk', workers=4,
        request_mode='nonthinking JSON object, source-free coverage per point plus independent source truth audit',
        controls=cases, request_count=sum(c['requests'] for c in cases),
        max_transport_attempts=1, content_retries=0, implementation_sha256=bindings,
        questions_sha256=sha(DATASET/'model/questions.json'),
        scoring_sha256={name:sha(DATASET/'scoring'/name) for name in ['annotations.json','evidence.json']},
        criteria='All seven controls satisfy every preregistered bound/dimension; unknown cannot satisfy a required exact expectation.',
        reference_status='Synthetic controls constructed from source-checked annotations; calibration is not human agreement or QA performance.',
        revision_reason='v1 source audit ignored a literal question constraint; add general question-bound reasoning. C03 exact .5 coverage expectation was too restrictive for overlapping partial content: require 0<coverage<1, retain complete=0. v1 remains failed and unchanged.',
        export_authorization='User explicitly authorized proxy 14B calibration, scoring and at most one targeted review per answer; no automatic review in this calibration.')
    save(a.output/'protocol.json', protocol)
    print(dict(controls=7, requests=protocol['request_count']))


def run(a):
    protocol = read(a.output/'protocol.json')
    for rel, digest in protocol['implementation_sha256'].items():
        if sha(PROJECT/rel) != digest: raise ValueError('Judge implementation drift: '+rel)
    for name, digest in protocol['scoring_sha256'].items():
        if sha(DATASET/'scoring'/name) != digest: raise ValueError('Calibration scoring data drift')
    def worker(case):
        folder = a.output/'sessions'/case['id']; result_path = folder/'result.json'
        if result_path.exists(): return read(result_path)
        payload_path = a.output/'payloads'/(case['id']+'.json')
        if sha(payload_path) != case['payload_sha256']: raise ValueError('Calibration input drift')
        result = judged(read(payload_path), folder)
        result.update(control=case['id'], expected=case['expected'], protocol_sha256=sha(a.output/'protocol.json'))
        metrics = result.get('metrics', {})
        result['passed'] = all(metrics.get(k) == v for k,v in case['expected'].items())
        if case['partial_coverage_required']:
            result['passed'] = result['passed'] and 0 < metrics.get('required_point_coverage_lower',0) < 1
        save(result_path, result)
        print(case['id'], result['status'], result['passed'], flush=True)
        return result
    results = []
    with ThreadPoolExecutor(max_workers=protocol['workers']) as pool:
        futures = [pool.submit(worker, case) for case in protocol['controls']]
        for future in as_completed(futures): results.append(future.result())
    completion = dict(controls=len(results), passed=sum(r['passed'] for r in results),
        calibration_passed=all(r['passed'] for r in results), protocol_sha256=sha(a.output/'protocol.json'),
        results_sha256={r['control']:sha(a.output/'sessions'/r['control']/'result.json') for r in results})
    save(a.output/'completion.json', completion)
    print(completion['calibration_passed'], flush=True)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('command', choices=['prepare','run'])
    p.add_argument('--output', type=Path, required=True)
    a=p.parse_args(); (prepare if a.command=='prepare' else run)(a)


if __name__=='__main__': main()
