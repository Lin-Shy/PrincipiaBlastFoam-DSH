"""Compare all fixed masked audit scores with prior AI opinions; never grant acceptance."""
import argparse
from pathlib import Path
from chapter2_prepare_local_actual_audit import read, sha
from chapter2_run_local_actual_audit import save


def compare(reference, score):
    """Unknown remains unknown; a prior AI opinion is not human ground truth."""
    expected = reference['complete_valid_answer']
    observed = score.get('metrics', {}).get('complete_valid_answer')
    if observed is not None and (type(observed) is not int or observed not in (0, 1)):
        raise ValueError('Invalid automatic completeness value')
    points = {p['id']:p['verdict'] for p in score.get('judgment', {}).get('points', [])}
    return dict(review_id=reference['review_id'], question_id=reference['question_id'],
                prior_ai_complete=expected, local_complete=observed,
                complete_comparison='unknown' if expected is None or observed is None else
                                    ('agrees' if expected == observed else 'disagrees'),
                point_comparisons=[dict(point_id=p['id'],prior_ai_verdict=p['verdict'],
                    local_verdict=points.get(p['id']),
                    same_label=None if p['id'] not in points else points[p['id']]==p['verdict'])
                    for p in reference['required_points']],
                local_status=score['status'], needs_source_review=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--activity',type=Path,required=True)
    args = parser.parse_args()
    root=args.activity.resolve();out=root/'development/local_actual_answer_audit_004'
    completion=read(out/'scoring-completion.json')
    if completion.get('answers')!=15 or len(completion['rows'])!=15:
        raise ValueError('All fifteen actual audit scores required')
    prep=read(out/'preparation.json')
    refpath=root/'development/actual_answer_review_001/evaluation_only/codex-verdicts.json'
    ref=read(refpath)
    if prep['inputs_sha256'].get(str(refpath.relative_to(root)))!=sha(refpath):
        raise ValueError('Prior AI opinion binding drift')
    if ref['human_truth'] is not False or ref['method_labels_shown_in_review_pack'] is not False:
        raise ValueError('Prior opinion masking/provenance mismatch')
    expected={r['review_id']:r for r in ref['verdicts']}
    prepared={r['review_id']:r for r in prep['rows']}
    if len(expected)!=15 or set(expected)!=set(prepared) or set(expected)!={r['review_id'] for r in completion['rows']}:
        raise ValueError('Fixed audit selection differs')
    rows=[];bindings={str(refpath):sha(refpath),str(out/'preparation.json'):sha(out/'preparation.json'),
                      str(out/'scoring-completion.json'):sha(out/'scoring-completion.json')}
    for item in completion['rows']:
        rid=item['review_id'];folder=out/'sessions'/rid;path=folder/'score.json';score=read(path)
        if sha(path)!=item['score_sha256'] or score['result_sha256']!=prepared[rid]['result_sha256']:
            raise ValueError('Actual score or answer drift')
        if score['review_id']!=rid or score['question_id']!=expected[rid]['question_id']:
            raise ValueError('Masked question identity drift')
        for name,value in score['request_bindings'].items():
            p=folder/'requests'/name
            if sha(p)!=value:raise ValueError('Actual response drift')
            bindings[str(p)]=value
        bindings[str(path)]=sha(path);rows.append(compare(expected[rid],score))
    save(out/'comparison.json',dict(schema='compact_local_actual_audit_comparison_v1',rows=rows,
         planned_answers=15,reviewed_answers=0,pending_answers=list(prepared),accepted=False,
         formal_result=False,human_truth=False,method_labels_masked=True,automatic_labels_replaced=False,
         model_calls=0,inputs_sha256=bindings,implementation_sha256=sha(Path(__file__))))
    print('All 15 masked score comparisons written; source review and acceptance still pending')


if __name__=='__main__':main()
