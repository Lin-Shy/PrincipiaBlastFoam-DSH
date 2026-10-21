"""只读审计；历史完整性清单用于第二轮结束时逐文件核验。"""
import argparse
from collections import Counter
import importlib.metadata
import platform
import subprocess
import time

from common import *

def inventory():
    roots = [CURRENT, RESOURCES, DATASET,
             WORKSPACE / 'graduation-thesis-materials/graduation-manuscript']
    return {p.relative_to(WORKSPACE).as_posix(): sha(p)
            for root in roots for p in sorted(root.rglob('*'))
            if p.is_file() and '.git' not in p.parts and '__pycache__' not in p.parts}

def git_state(root):
    cmd = ['git', '-c', 'safe.directory=' + root.as_posix(), '-C', str(root)]
    def run(args):
        result = subprocess.run(cmd + args, capture_output=True, text=True, encoding='utf-8')
        return result.stdout.strip() if result.returncode == 0 else result.stderr.strip()
    status = run(['status', '--porcelain'])
    return dict(commit=run(['rev-parse', 'HEAD']), status=status.splitlines(),
                submodules=run(['submodule', 'status']))

def prepare():
    out = ARCHIVE / 'audit'
    if (out / 'historical_before.json').exists():
        raise FileExistsError('audit already started; use verify for preservation')
    started = time.monotonic()
    save(out / 'historical_before.json', inventory())
    p = read(HISTORICAL / 'protocol.json')
    bindings = {k: dict(expected=v, actual=sha(PROJECT / k), matches=sha(PROJECT / k) == v,
                       snapshot_matches=sha(HISTORICAL / 'runtime' / k) == v)
                for k, v in p['implementation_sha256'].items()}
    resources = {k: sha(RESOURCES / k) == v for k, v in p['source_resources'].items()}
    resources.update({'e5/' + k: sha(RESOURCES / 'e5' / k) == v for k, v in p['e5_resources'].items()})
    annotations = read(DATASET / 'scoring/annotations.json')
    evidence = read(DATASET / 'scoring/evidence.json')
    graph = read(GRAPH)
    source_hashes = read(RESOURCES / 'source-map.json')['files']
    corpus_ok = all(sha(RESOURCES / 'corpus' / k) == v for k, v in source_hashes.items())
    counts = dict(questions=len(public_questions()), themes=len({r['theme_id'] for r in annotations}),
                  groups=len({r['split_group'] for r in annotations}),
                  types=dict(Counter(r['labels']['evidence_integration'] + '_' + str(r['labels']['condition_discrimination']) for r in annotations)),
                  points=sum(len(r['required_points']) for r in annotations), evidence=len(evidence),
                  evidence_files=len({r['path'] for r in evidence.values()}), corpus_files=len(source_hashes),
                  graph_nodes=len(graph['nodes']), graph_edges=len(graph['edges']), graph_units=len(graph['units']),
                  aliases=graph['bilingual_alias_revision'])
    dataset_ok = all(sha(DATASET / 'scoring' / k) == v for k, v in p['scoring_data_sha256'].items())
    q_ok = sha(QUESTIONS) == p['questions_sha256']
    checks = dict(code=all(v['matches'] and v['snapshot_matches'] for v in bindings.values()),
                  resources=all(resources.values()), corpus=corpus_ok, scoring=dataset_ok, questions=q_ok,
                  graph=sha(GRAPH) == p['construction_graph_sha256'])
    env = {n: importlib.metadata.version(n) for n in ['numpy', 'pytest', 'huggingface-hub', 'transformers']}
    result = dict(schema='round2_readonly_audit_v1', checks=checks, counts=counts,
                  implementation_bindings=bindings, resource_bindings=resources,
                  historical_protocol_sha256=sha(HISTORICAL / 'protocol.json'),
                  graph_sha256=sha(GRAPH), public_questions_sha256=sha(QUESTIONS),
                  git={n: git_state(WORKSPACE / n) for n in ['PrincipiaBlastFoam-DSH', 'graduation-experiment-results', 'graduation-thesis-materials']},
                  environment=dict(python=sys.version, executable=sys.executable, platform=platform.platform(), packages=env),
                  audit_seconds=time.monotonic()-started,
                  scoring_boundary='This audit process may read scoring. Retrieval processes cannot import this module.')
    save(out / 'checks.json', result)
    print(wire(dict(checks=checks, counts=counts, historical_files=len(read(out / 'historical_before.json')))))
    if not all(checks.values()):
        raise ValueError('historical binding mismatch; comparisons blocked')

def verify(output):
    before = read(ARCHIVE / 'audit/historical_before.json')
    after = inventory()
    changed = [k for k, v in before.items() if after.get(k) != v]
    added = sorted(set(after) - set(before))
    save(ARCHIVE / 'audit' / output, dict(files_checked=len(before), changed_or_missing=changed,
                                       added=added, preserved=not changed and not added))
    print(wire(dict(files_checked=len(before), changed=len(changed), added=len(added))))
    if changed or added:
        raise ValueError('historical inventory changed')

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['prepare', 'verify'])
    parser.add_argument('--output', default='historical_preservation.json')
    args = parser.parse_args()
    prepare() if args.action == 'prepare' else verify(args.output)
