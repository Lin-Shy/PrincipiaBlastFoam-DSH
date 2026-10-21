"""Verify all masked source reviews and record an explicit AI admission decision."""
import argparse
from collections import Counter
import json
from pathlib import Path
from chapter2_prepare_local_actual_audit import read, sha
from chapter2_run_local_actual_audit import save, validate_controls
from chapter2_local_judge_costs import physical_local_cost
from chapter2_local_compact_score_execution import request_sha


def verify_review(row, source, folder, corpus):
    if (row.get('question_id') != source['question_id']
            or row.get('changes_to_automatic_score') is not False
            or type(row.get('reasoning')) is not str or not row['reasoning'].strip()):
        raise ValueError('Personal review identity, reasoning or score replacement invalid')
    value = row.get('reviewer_complete')
    if value is not None and (type(value) is not int or value not in (0, 1)):
        raise ValueError('Personal primary opinion must be 0, 1 or unknown')
    expected_items = {'question', 'actual candidate', 'all required hypotheses',
                      'all raw stage judgments', 'bound original source spans'}
    if set(row.get('reviewed_items', [])) != expected_items:
        raise ValueError('Personal review scope incomplete')
    score = read(folder/'score.json')
    files = sorted((folder/'requests').glob('*.json'))
    if (row.get('score_sha256') != sha(folder/'score.json')
            or row.get('local_complete') != score['metrics']['complete_valid_answer']
            or row.get('request_sha256') != {p.name:sha(p) for p in files}):
        raise ValueError('Personally reviewed score or stage response drift')
    if len(files) != len(score['raw_stage_judgments']):
        raise ValueError('Personal review does not cover every actual stage')
    for path, judgment in zip(files, score['raw_stage_judgments']):
        raw = read(path)['raw_response']['choices'][0]['message']['content']
        if json.loads(raw) != judgment:
            raise ValueError('Raw judgment differs from reviewed score')
    spans = list(source['original_material'].values())
    if row.get('originals') != [{k:s[k] for k in ('path','sha256','start','end')} for s in spans]:
        raise ValueError('Personal review original-source scope differs')
    for span in spans:
        path = corpus/span['path'];lines = path.read_text(encoding='utf-8').splitlines()
        if sha(path) != span['sha256'] or any(lines[l['number']-1] != l['text'] for l in span['lines']):
            raise ValueError('Personally reviewed original-source drift')
    return value


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--activity', type=Path, required=True)
    p.add_argument('--native-observation', type=Path, required=True)
    p.add_argument('--decision', type=Path, required=True)
    a = p.parse_args();root = a.activity.resolve()
    out = root/'development/local_actual_answer_audit_004'
    bindings = validate_controls(root)
    native = read(a.native_observation);completion = read(out/'scoring-completion.json')
    if (native.get('schema') != 'local_actual_audit_root_native_observation_v1'
            or native.get('native_returncode') != 0 or type(native.get('root_tool_session')) is not int
            or native.get('completion_sha256') != sha(out/'scoring-completion.json')
            or native.get('execution_registration_sha256') != sha(out/'execution-registration.json')):
        raise ValueError('Externally observed native exit zero required')
    prep = read(out/'preparation.json');budget = read(out/'input-budget.json')
    for name, value in read(out/'execution-registration.json')['input_sha256'].items():
        if sha(Path(name)) != value:raise ValueError('Registered execution input drift')
    for data in (prep,budget):
        for name,value in data['inputs_sha256'].items():
            path=Path(name)
            if not path.is_absolute():path=root/path
            if sha(path)!=value:raise ValueError('Prepared input/budget drift')
    inputs_path = root/'development/actual_answer_review_001/evaluation_only/inputs.json'
    inputs = {r['review_id']:r for r in read(inputs_path)}
    expected = {r['review_id']:r for r in prep['rows']}
    if (len(expected) != 15 or len(inputs) != 15 or set(expected) != set(inputs)
            or completion.get('answers') != 15 or len(completion['rows']) != 15
            or {r['review_id'] for r in completion['rows']} != set(expected)):
        raise ValueError('All fixed fifteen answer identities required')
    completed = {r['review_id']:r for r in completion['rows']}
    budgets = {r['review_id']:r for r in budget['rows']}
    corpus = Path(read(root/'development/formal_preparation_005/local-resources.json')['corpus'])
    reviews = {};request_files = [];results = []
    prior_path = root/'development/actual_answer_review_001/evaluation_only/codex-verdicts.json'
    prior = {r['review_id']:r for r in read(prior_path)['verdicts']}
    for batch_path in sorted(out.glob('semantic-review-batch-*.json')):
        batch = read(batch_path)
        if (batch.get('schema') != 'local_actual_answer_semantic_review_batch_v1'
                or batch.get('human_truth') is not False or batch.get('method_labels_masked') is not True
                or batch.get('candidate') != 'compact_local_004'):
            raise ValueError('Personal review provenance or masking invalid')
        for row in batch['rows']:
            rid = row['review_id']
            if rid not in expected or rid in reviews:raise ValueError('Missing or duplicated personal review identity')
            folder = out/'sessions'/rid
            verify_review(row,inputs[rid],folder,corpus)
            score = read(folder/'score.json');files = sorted((folder/'requests').glob('*.json'))
            if (score.get('review_id') != rid or score.get('question_id') != inputs[rid]['question_id']
                    or row['prior_ai_complete'] != prior[rid]['complete_valid_answer']
                    or sha(folder/'score.json') != completed[rid]['score_sha256']
                    or score['result_sha256'] != expected[rid]['result_sha256']
                    or sha(root/expected[rid]['result_relative_path']) != expected[rid]['result_sha256']
                    or score['request_bindings'] != {p.name:sha(p) for p in files}):
                raise ValueError('Completed score/answer binding drift')
            stages = budgets[rid]
            if len(files) != len(stages['actual_request_sha256']):
                raise ValueError('Actual development audit stage coverage incomplete')
            for index,path in enumerate(files):
                record = read(path);raw = record['raw_response'];usage = raw.get('usage',{})
                if (path.name != f'{index:02d}.json' or record.get('provider') != 'qwen_local'
                        or record.get('transport_attempts') != 1 or record.get('status') != 'response'
                        or record.get('request_sha256') != stages['actual_request_sha256'][index]
                        or request_sha(record['request']) != stages['actual_request_sha256'][index]
                        or raw.get('model') != record['request']['model']
                        or usage.get('prompt_tokens') != stages['actual_input_tokens'][index]
                        or type(usage.get('completion_tokens')) is not int
                        or not 0 <= usage['completion_tokens'] <= 4096):
                    raise ValueError('Actual stage identity or physical token accounting invalid')
                bindings[str(path)] = sha(path)
            request_files.extend(files);reviews[rid] = row
            results.append(dict(review_id=rid,question_id=row['question_id'],
                prior_ai_complete=row['prior_ai_complete'],reviewer_complete=row['reviewer_complete'],
                local_complete=row['local_complete'],primary_assessment=row['primary_assessment']))
            bindings[str(folder/'score.json')] = sha(folder/'score.json')
        bindings[str(batch_path)] = sha(batch_path)
    if set(reviews) != set(expected) or len(request_files) != 55:
        raise ValueError('All fifteen source reviews and fifty-five stage responses required')
    decision = read(a.decision)
    if (decision.get('schema') != 'local_actual_audit_explicit_ai_decision_v1'
            or type(decision.get('accepted')) is not bool or decision.get('human_truth') is not False
            or decision.get('method_labels_masked') is not True
            or decision.get('automatic_labels_replaced') is not False
            or not decision.get('rationale') or not decision.get('limitations')
            or decision.get('review_batches_sha256') != {
                p.name:sha(p) for p in sorted(out.glob('semantic-review-batch-*.json'))}):
        raise ValueError('Complete, explicit, source-bound AI decision required')
    comparisons = Counter('unknown' if r['reviewer_complete'] is None or r['local_complete'] is None
                          else ('agrees' if r['reviewer_complete'] == r['local_complete'] else 'disagrees')
                          for r in results)
    for path in [a.native_observation,a.decision,inputs_path,prior_path,out/'preparation.json',out/'input-budget.json',
                 out/'execution-registration.json',out/'scoring-completion.json',out/'comparison.json']:
        bindings[str(path)] = sha(path)
    report = dict(schema='compact_local_actual_audit_source_report_v1',formal_result=False,
        planned_answers=15,reviewed_answers=15,pending_answers=[],accepted=decision['accepted'],
        human_truth=False,method_labels_masked=True,automatic_labels_replaced=False,
        root_tool_session=native['root_tool_session'],native_returncode=0,rows=results,
        primary_comparison_to_current_ai_review=dict(comparisons),
        rationale=decision['rationale'],limitations=decision['limitations'],
        physical_costs=physical_local_cost(request_files),inputs_sha256=bindings,
        implementation_sha256=sha(Path(__file__)),network_requests=0,credentials_loaded=False)
    save(out/'report.json',report)
    print(json.dumps(dict(reviewed_answers=15,accepted=decision['accepted'],primary_comparison=dict(comparisons))))


if __name__ == '__main__':main()
