"""隔离评分层导出预定类型的首个检索案例，核验必要证据覆盖；无模型调用。"""
import argparse
import hashlib
import json
from pathlib import Path
import sys


def load(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--scores', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    sys.path.insert(0, str(root / 'runtime'))
    from chapter2_formal_runtime import verify
    protocol, protocol_sha = verify(root, require_snapshot=False)
    scores = load(args.scores)
    if scores['protocol_sha256'] != protocol_sha or scores['completed_native_queries'] != 2592:
        raise ValueError('需要完整冻结检索网格')
    annotation_path = Path(protocol['private_scoring_input']['path'])
    if sha(annotation_path) != protocol['private_scoring_input']['sha256']:
        raise ValueError('gold哈希漂移')
    annotations = {a['id']: a for a in load(annotation_path)}
    records = {(r['key'], r['arm']): r for r in scores['rows']}
    keys = sorted({r['key'] for r in scores['rows'] if r['category'] == 'cross' and r['repeat'] == 1})
    def complete(k, arm):
        return records[k, arm]['by_budget']['24000']['complete_evidence_set_success']
    criteria = [('跨来源路径补齐', lambda k: complete(k, 'full') and not complete(k, 'no_cross')),
                ('完整方法仍失败', lambda k: not complete(k, 'full')),
                ('取消作用域后缺失', lambda k: complete(k, 'full') and not complete(k, 'no_scope'))]
    corpus = Path(protocol['paths']['corpus'])
    cases, hashes = [], {}
    for label, select in criteria:
        key = next(k for k in keys if select(k))
        baseline = load(root / 'native/full' / (key+'.json'))
        ann = annotations[baseline['question']['family_id']]
        atoms = []
        for atom in ann['evidence']:
            source = corpus / atom['path']
            lines = source.read_text().splitlines()
            if sha(source) != atom['sha256'] or '\n'.join(lines[atom['start']-1:atom['end']]) != atom['quote']:
                raise ValueError('案例原文不一致')
            atoms.append(atom)
        comparisons = []
        for arm in ['full', 'no_cross', 'no_scope', 'e5']:
            file = root / 'native' / arm / (key+'.json')
            hashes[str(file.relative_to(root))] = sha(file)
            native = load(file)
            units = native['deliveries']['24000']['units']
            coverage = []
            for atom in atoms:
                delivered = set()
                for u in units:
                    if u.get('mapping_status') != 'unmappable' and u['path'] == atom['path'] and u['source_sha256'] == atom['sha256']:
                        delivered.update(range(u['start'], u['end']+1))
                coverage.append(all(n in delivered for n in range(atom['start'], atom['end']+1)))
            if int(all(coverage)) != complete(key, arm):
                raise ValueError('案例逐行覆盖与冻结主指标不一致')
            wrong = [u for u in units if u.get('mapping_status') != 'unmappable' and u.get('case_id') and u['source_kind'] == 'tutorial' and u['case_id'].removeprefix('tutorials/') not in ann['cases']]
            comparisons.append({'arm': arm, 'covered_gold_atoms': coverage,
                'complete': int(all(coverage)), 'wrong_case_proxy': records[key, arm]['scope_case_proxy'],
                'first_three_outside_target_case_units': [{k: u.get(k) for k in ['path','start','end','case_id','scope_id']} for u in wrong[:3]]})
        cases.append({'kind': label, 'key': key, 'question': baseline['question'], 'gold_evidence': atoms, 'comparisons': comparisons})
    result = {'schema': 'formal-retrieval-qualitative-case-evidence-v1', 'protocol_sha256': protocol_sha,
              'selection': 'for each stated predicate: first sorted cross-source repeat1 key; no answer quality used',
              'score_sha256': sha(args.scores), 'script_sha256': sha(Path(__file__)),
              'cases': cases, 'native_response_sha256': hashes, 'new_llm_calls': 0,
              'limits': 'illustrative retrieval cases only, not human review or exhaustive semantic audit; out-of-case evidence may be ancillary rather than wrong; no retuning'}
    if args.output.exists():
        raise FileExistsError('new isolated case audit required')
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')


if __name__ == '__main__':
    main()
