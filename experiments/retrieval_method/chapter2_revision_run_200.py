"""Approved metric/graph revision: 600 fresh answers, 800 explicitly reused baselines."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import sys

from chapter2_optimization_200 import PROJECT, DATASET, read, save, sha
import chapter2_publication_200 as original
from chapter2_selected_graph_200 import backend

PROFILES = {'graph': 'selected', 'graph_no_cross': 'no_cross', 'graph_no_aliases': 'no_aliases'}
BASELINES = ['bm25', 'e5', 'hybrid', 'none']


def prepare(root, old):
    if (root/'protocol.json').exists():
        raise FileExistsError('Revision protocol already frozen')
    p = read(root/'provenance/baseline-generation-protocol.json')
    scoring = read(root/'provenance/baseline-scoring-protocol.json')
    closed = read(root/'provenance/baseline-scoring-completion.json')
    old_sha = sha(root/'provenance/baseline-generation-protocol.json')
    scoring_sha = sha(root/'provenance/baseline-scoring-protocol.json')
    if scoring['formal_protocol_sha256'] != old_sha or closed['execution_protocol_sha256'] != scoring_sha:
        raise ValueError('Baseline protocol identity drift')
    qs = read(DATASET/'model/questions.json')
    if len(qs) != 200 or any(set(q) != {'id','question'} for q in qs):
        raise ValueError('Public-only exact 200 bank required')
    baseline_bindings = {}
    for arm in BASELINES:
        completion = read(root/'reused/completion'/(arm+'.json'))
        if completion['protocol_sha256'] != old_sha or completion['sessions'] != 200:
            raise ValueError('Incomplete reused arm')
        for q in qs:
            key = arm+'/'+q['id']
            result = root/'reused/generation'/arm/q['id']/'result.json'
            score = root/'reused/scoring/sessions'/arm/q['id']/'result.json'
            if sha(result) != completion['results_sha256'][q['id']] or sha(score) != closed['results_sha256'][key]:
                raise ValueError('Reused evidence drift: '+key)
            row = read(score)
            if row['generation_sha256'] != sha(result) or row['execution_protocol_sha256'] != scoring_sha:
                raise ValueError('Reused score binding drift')
            baseline_bindings[key] = dict(generation_sha256=sha(result), scoring_sha256=sha(score))
    bindings = dict(p['implementation_sha256'])
    for rel, digest in bindings.items():
        source = old/'runtime'/rel
        if sha(source) != digest or sha(PROJECT/rel) != digest:
            raise ValueError('Frozen implementation drift: '+rel)
        target = root/'runtime'/rel
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(source.read_bytes())
    for name in ['chapter2_revision_run_200.py','chapter2_revision_generation_audit.py',
                 'chapter2_selected_graph_200.py','chapter2_metric_revision_200.py']:
        source = Path(__file__).with_name(name)
        rel = source.relative_to(PROJECT).as_posix()
        bindings[rel] = sha(source)
        target = root/'runtime'/rel
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(source.read_bytes())
    calibration = root/'calibration'
    cal = read(calibration/'completion.json')
    if not cal['calibration_passed'] or cal['passed'] != 7:
        raise ValueError('All seven calibration controls required')
    if cal['protocol_sha256'] != sha(calibration/'protocol.json'):
        raise ValueError('Calibration binding drift')
    for key, digest in cal['results_sha256'].items():
        if sha(calibration/'sessions'/key/'result.json') != digest:
            raise ValueError('Calibration result drift')
    manifest = read(root/'graphs/manifest.json')
    for name in PROFILES.values():
        if sha(root/'graphs'/(name+'.json')) != manifest['profiles'][name]['sha256']:
            raise ValueError('Graph drift')
    save(root/'public-questions.json',qs)
    p.update(schema='publication_200_metric_graph_revision_v2',status='frozen_before_generation',
        arms=list(PROFILES),generation_sessions=600,workers_per_arm=2,max_concurrent_answer_requests=6,
        comparison_arms=['graph']+BASELINES+['graph_no_cross','graph_no_aliases'],
        public_questions_sha256=sha(root/'public-questions.json'),implementation_sha256=bindings,
        graphs={name:sha(root/'graphs'/(name+'.json')) for name in PROFILES.values()},
        graph_profiles=PROFILES,graph_manifest_sha256=sha(root/'graphs/manifest.json'),
        graph_selection='Post-result empirical selection of the previously evaluated condition-free graph; same exposed 200-question bank; fresh full graph and both ablations',
        construction_graph_sha256=sha(root/'graphs/selected.json'),
        graph_method='Source-unit bilingual graph, structured conditions disabled; natural source conditions retained; physical source-association and generated-Chinese-alias ablations',
        design_sha256=sha(root/'provenance/adopted-chapter02.md'),
        reused_baselines=dict(arms=BASELINES,sessions=800,bindings=baseline_bindings,
            generation_protocol_sha256=old_sha,scoring_protocol_sha256=scoring_sha,
            scoring_completion_sha256=sha(root/'provenance/baseline-scoring-completion.json'),
            rule='Actual prior raw answers and frozen judge records; never relabel their protocol as this revision. Four-baseline comparisons span batches; three graph arms share this batch.'))
    p['judge'].update(calibration=str(calibration.resolve()),
        calibration_protocol_sha256=sha(calibration/'protocol.json'),
        calibration_completion_sha256=sha(calibration/'completion.json'))
    p['statistics'].update(primary='End-to-end effective answer score, 100 * mean(C_i * F_i * A_i), all 200 questions',
        coverage='Frozen required-point weighted coverage: full=1, partial=0.5, omitted/wrong=0; unknowns bounded',
        factuality_gate='Frozen factuality pass=1, fail=0, unknown=[0,1]; failed generation=0',
        applicability_gate='Frozen applicability pass=1, fail=0, unknown=[0,1]; nonconditional question=1',
        secondary='Original strict complete-valid answer rate, unchanged: C_i=1 and the same truth/applicability gates',
        units='Primary is score points on [0,100], not percent of wholly correct questions',
        adoption='Primary metric changed after inspecting prior results, explicitly approved by user; rubric and raw baseline judgments remain unchanged',
        comparison_families=dict(primary=['graph vs '+arm for arm in BASELINES],
            ablation=['graph vs graph_no_cross','graph vs graph_no_aliases']))
    save(root/'protocol.json',p)
    print(json.dumps(dict(fresh_sessions=600,reused_sessions=800,workers=6,
        protocol_sha256=sha(root/'protocol.json'))),flush=True)


def answer(root, arm):
    p = original.verify(root)
    if arm not in PROFILES or p['graph_profiles'] != PROFILES:
        raise ValueError('Unknown graph profile')
    # Retain the exact frozen autonomous consumer, tokenizer, deployment,
    # prompts, budgets and result schema. Only graph construction changes.
    original.ARMS = list(PROFILES)
    original.engine = lambda key, ignored_path: backend(root/'graphs',PROFILES[arm])
    original.answer(argparse.Namespace(output=root,arm=arm))


def run(root):
    p = original.verify(root)
    def worker(arm):
        log = root/'logs'/(arm+'.log')
        log.parent.mkdir(exist_ok=True)
        if (root/'completion'/(arm+'.json')).exists():
            return arm,0
        with log.open('a',encoding='utf-8') as output:
            done = subprocess.run([sys.executable,'-X','utf8',str(Path(__file__).resolve()),
                'answer','--root',str(root),'--arm',arm],cwd=PROJECT,stdout=output,stderr=subprocess.STDOUT)
        print(arm,'exit',done.returncode,flush=True)
        return arm,done.returncode
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(worker,p['arms']))
    save(root/'generation-controller-completion.json',dict(arms=dict(results),
        complete=all(code==0 for _,code in results),protocol_sha256=sha(root/'protocol.json')))


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['prepare','answer','run'])
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--old',type=Path)
    parser.add_argument('--arm',choices=list(PROFILES))
    args=parser.parse_args();root=args.root.resolve()
    if args.command=='prepare':prepare(root,args.old.resolve())
    elif args.command=='answer':answer(root,args.arm)
    else:run(root)
