"""验证五分制结果、冻结身份、导出安全与JS/Python校验互通。"""
import copy
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from experiments.retrieval_method import chapter2_human_rating as rating


@pytest.fixture
def frozen(tmp_path):
    experiment = tmp_path / 'experiment'
    root = experiment / 'formal/frozen_001'
    root.mkdir(parents=True)
    protocol = {'planned_sessions': 48, 'human_review': {'sessions': 48}}
    rating.write(root / 'protocol.json', protocol)
    protocol_sha = rating.digest(root / 'protocol.json')
    rating.write(root / 'seal.json', {'protocol_sha256': protocol_sha})
    cases, identity, model = [], {}, []
    for i in range(48):
        blind = f'B{i:04d}'
        arm = list(rating.LABELS)[i % 6]
        cases.append(dict(blind_id=blind, question='原题中文', answer_text='原答案 </script><img src=x onerror=alert(1)>',
                          references=[], gold_evidence=[], allowed=[], forbidden=[], ambiguity=[], gold_points=[], human_notes=''))
        identity[blind] = dict(arm=arm, family_id=f'F{i // 6:03d}', question_id=f'Q{i // 6:03d}', repeat=1, answer_sha256='a' * 64)
        model.append(dict(blind_id=blind, **identity[blind], strict_outcome='unknown' if i == 0 else 'failure',
                          strict_bounds=[0, 1], citation_accuracy_bounds=[0, 1], citation_state='unknown', unknown_criteria=1))
    (root / 'human_review').mkdir()
    rating.write(root / 'human_review/blind_sample.json', {'protocol_sha256': protocol_sha, 'cases': cases})
    (root / 'completion').mkdir()
    rating.write(root / 'completion/review_prepare.json', {'human_sample_sha256': rating.digest(root / 'human_review/blind_sample.json')})
    (root / 'evaluation_only').mkdir()
    rating.write(root / 'evaluation_only/identity.json', identity)
    scores = tmp_path / 'scores.json'
    rating.write(scores, dict(protocol_sha256=protocol_sha, incomplete_grid_analysis=True,
                             sessions_in_frozen_denominator=48, rows=model))
    return experiment, scores


def document(binding, ids, score=5):
    d = dict(schema=rating.SCHEMA, binding=binding, reviewer=dict(id='测试审阅者', participated_in_development=False, previously_exposed=False),
             rows=[dict(blind_id=i, claim_correctness=score, citation_support=score, notes='', updated_at='2026-10-07T01:00:00.000Z') for i in ids],
             created_at='2026-10-07T00:00:00.000Z', finalized_at='2026-10-07T02:00:00.000Z',
             revision_phase='blind', parent_seal_sha256=None, status='sealed')
    d['sealed_payload_sha256'] = rating.seal_digest(d)
    return d


def context(frozen):
    cases, binding, _, _ = rating.frozen_inputs(*frozen)
    return binding, [c['blind_id'] for c in cases]


def test_build_is_blind_and_verbatim_and_non_overwriting(frozen, tmp_path):
    output = tmp_path / 'delivery'
    result = rating.build(*frozen, output)
    html = (output / '人工评分.html').read_text()
    assert '</script><img' not in html
    assert '\\u003c/script>' in html
    assert '原题中文' in html
    assert 'model_claimed_success' in html  # generic UI vocabulary, no model observations
    embedded = html.split('<script id="review-data" type="application/json">')[1].split('</script>')[0]
    data = json.loads(embedded)
    assert set(data) == {'schema', 'binding', 'cases', 'unblind_sha256'}
    assert not any(k in c for c in data['cases'] for k in ('arm', 'identity', 'model', 'human_notes'))
    assert data['cases'][0]['answer_text'].startswith('原答案 </script>')
    assert result['human_completed'] == result['model_calls'] == 0
    assert data['unblind_sha256'] == rating.digest(output / 'unblind.json')
    with pytest.raises(FileExistsError):
        rating.build(*frozen, output)


@pytest.mark.parametrize('change', ['hash', 'duplicate', 'missing', 'fraction', 'bool', 'empty', 'tamper', 'background', 'time', 'revision'])
def test_reject_invalid_results(frozen, change):
    binding, ids = context(frozen)
    d = document(binding, ids)
    if change == 'hash':
        d['binding'] = {**binding, 'sample_sha256': '0' * 64}
    elif change == 'duplicate':
        d['rows'][1]['blind_id'] = ids[0]
    elif change == 'missing':
        d['rows'].pop()
    elif change == 'fraction':
        d['rows'][0]['claim_correctness'] = 2.5
    elif change == 'bool':
        d['rows'][0]['claim_correctness'] = True
    elif change == 'empty':
        d['rows'][0]['citation_support'] = None
    elif change == 'tamper':
        d['rows'][0]['claim_correctness'] = 1
    elif change == 'background':
        d['reviewer']['previously_exposed'] = None
    elif change == 'time':
        d['finalized_at'] = d['created_at']
    else:
        d['revision_phase'] = 'post_unblind'
    with pytest.raises(ValueError):
        rating.validate(d, binding, ids)


def test_blank_notes_uncertain_stats_and_unknowns_preserved(frozen, tmp_path):
    binding, ids = context(frozen)
    d = document(binding, ids, 'uncertain')
    ratings = tmp_path / 'ratings.json'
    rating.write(ratings, d)
    summary = rating.analyze(*frozen, ratings, tmp_path / 'analysis')
    assert summary['overall']['claim_correctness']['mean'] is None
    assert summary['overall']['citation_support']['uncertain'] == 48
    assert summary['rows'][0]['model']['strict_outcome'] == 'unknown'
    assert all(r['human']['notes'] == '' for r in summary['rows'])
    assert summary['families'] == 8
    with pytest.raises(FileExistsError):
        rating.analyze(*frozen, ratings, tmp_path / 'analysis')


def test_changed_identity_and_sample_rejected(frozen):
    experiment, scores = frozen
    d = rating.read(scores)
    d['rows'][0]['arm'] = 'e5'
    scores.write_text(json.dumps(d))
    with pytest.raises(ValueError, match='身份'):
        rating.frozen_inputs(experiment, scores)
    path = experiment / 'formal/frozen_001/human_review/blind_sample.json'
    path.write_text(path.read_text() + ' ')
    with pytest.raises(ValueError, match='哈希'):
        rating.frozen_inputs(experiment, scores)


def test_post_unblind_and_draft(frozen):
    binding, ids = context(frozen)
    d = document(binding, ids)
    d['parent_seal_sha256'] = d['sealed_payload_sha256']
    d['revision_phase'] = 'post_unblind'
    d['sealed_payload_sha256'] = rating.seal_digest(d)
    rating.validate(d, binding, ids)
    d.update(status='draft', finalized_at=None, sealed_payload_sha256=None)
    d['rows'][0].update(claim_correctness=None)
    rating.validate(d, binding, ids, require_sealed=False)
    with pytest.raises(ValueError, match='封存'):
        rating.validate(d, binding, ids)


def test_javascript_python_roundtrip(frozen, tmp_path):
    if not shutil.which('node'):
        pytest.skip('Node unavailable')
    binding, ids = context(frozen)
    d = document(binding, ids)
    d['rows'][0]['notes'] = '=危险公式\n备注,"中文"'
    d['sealed_payload_sha256'] = rating.seal_digest(d)
    input_path = tmp_path / 'input.json'
    rating.write(input_path, d)
    js = Path(rating.__file__).with_name('human_rating.js')
    code = '''const fs=require('fs'),core=require(process.argv[1]);
    (async()=>{const d=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
    await core.validate(d,d.binding,d.rows.map(r=>r.blind_id));
    const csv=core.csv(d); if(!csv.includes("'=危险公式"))throw Error('CSV unsafe');
    if(core.distribution(d.rows,'claim_correctness').mean!==5)throw Error('bad stats');
    d.rows[0].citation_support='uncertain';d.sealed_payload_sha256=await core.hash(core.canonical(core.payload(d)));
    console.log(JSON.stringify(d));})().catch(e=>{console.error(e);process.exit(1)});'''
    completed = subprocess.run(['node', '-e', code, str(js), str(input_path)], capture_output=True, text=True, check=True)
    result = json.loads(completed.stdout)
    rating.validate(result, binding, ids)
    assert result['rows'][0]['citation_support'] == 'uncertain'
    assert rating.csv_safe(' =1') == "' =1"
