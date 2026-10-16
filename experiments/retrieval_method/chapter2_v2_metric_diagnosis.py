"""Read-only decomposition of existing scores, without redefining success."""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def macro(rows, getter):
    questions = defaultdict(list)
    groups = {}
    for row in rows:
        value = getter(row)
        if value is None:
            continue
        questions[row['question_id']].append(value)
        groups[row['question_id']] = row['group']
    grouped = defaultdict(list)
    for qid, values in questions.items():
        grouped[groups[qid]].append([sum(v[i] for v in values)/len(values) for i in (0,1)])
    result = [sum(sum(v[i] for v in values)/len(values) for values in grouped.values())/len(grouped) for i in (0,1)]
    return dict(bounds=result, questions=len(questions),groups=len(grouped))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('observations','dataset','output'):
        parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args()
    annotations={r['id']:r for r in read(args.dataset/'scoring/annotations.json')}
    data=read(args.observations)
    series=defaultdict(list)
    for row in data:
        if row['cell_id'].startswith('main/'):
            series[row['cell_id'].split('/')[1]].append({**row,'group':annotations[row['question_id']]['split_group']})
    output={}
    for name,rows in series.items():
        def coverage(row):
            if row['generation_status']!='answered':return [0,0]
            metrics=row.get('auxiliary_metrics') or {}
            return [metrics.get('required_point_coverage_lower',0),metrics.get('required_point_coverage_upper',1)]
        def factual(row):
            if row['generation_status']!='answered':return [0,0]
            verdict=(row.get('auxiliary_metrics') or {}).get('factuality','unknown')
            return [int(verdict=='pass'),int(verdict!='fail')]
        def condition(row):
            if not annotations[row['question_id']]['labels']['condition_discrimination']:return None
            if row['generation_status']!='answered':return [0,0]
            verdict=(row.get('auxiliary_metrics') or {}).get('applicability','unknown')
            return [int(verdict=='pass'),int(verdict!='fail')]
        output[name]=dict(planned_observations=len(rows),
            strict_complete=macro(rows,lambda r:r['fixed_primary_bounds']),
            required_point_coverage=macro(rows,coverage),
            end_to_end_factual_acceptability=macro(rows,factual),
            conditional_answer_acceptability=macro(rows,condition),
            generation_status=dict(Counter(r['generation_status'] for r in rows)))
    evidence=read(args.dataset/'scoring/evidence.json')
    split=read(args.dataset/'split.json')
    devgroups={annotations[q]['split_group'] for q in split['ids']['dev']}
    testgroups={annotations[q]['split_group'] for q in split['ids']['test']}
    if devgroups&testgroups:raise ValueError('Knowledge group split leakage')
    point_counts=Counter(len(a['required_points']) for a in annotations.values())
    # These are metadata consistency checks. Whether a point is truly necessary
    # needs original-source/content review, not a rule based on model failure.
    diagnostics=dict(question_count=len(annotations), dev_count=len(split['ids']['dev']),test_count=len(split['ids']['test']),
        development_groups=len(devgroups),test_groups=len(testgroups),group_overlap=sorted(devgroups&testgroups),
        required_point_count_histogram=dict(sorted(point_counts.items())),evidence_spans=len(evidence),
        legacy_split_status=split.get('status'),metadata_status_is_not_the_authority_for_the_frozen_dataset=True)
    value=dict(schema='existing_frozen_score_decomposition_v2_development',formal_result=False,
        posthoc_descriptive=True,source_observations_sha256=digest(args.observations),
        source_annotations_sha256=digest(args.dataset/'scoring/annotations.json'),
        aggregation='repeats within question, questions within linked group, equal group macro',
        series=output,dataset_diagnostics=diagnostics,
        interpretation=['Coverage is weighted knowledge-point coverage with partial=.5, inherited unchanged from the existing rubric.',
            'Coverage is not strict complete-answer success, factuality, or an accuracy improvement.',
            'Unknown dimensions retain [0,1]; generation failures are end-to-end zeros.',
            'Conditional metric excludes nonconditional questions by preexisting question labels, not by observed outcomes.',
            'Descriptive metric decomposition cannot create confirmatory superiority or repair dataset validity.'])
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x',encoding='utf-8') as stream:json.dump(value,stream,ensure_ascii=False,indent=2)
    print(json.dumps(output),flush=True)


if __name__=='__main__':main()
