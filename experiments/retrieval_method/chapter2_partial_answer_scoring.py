"""v7 preserves a known required-point failure when a later dimension is unknown.

No raw response or semantic verdict is repaired. A complete answer requires ALL
necessary points; a validated omission/partial/contradiction already proves
failure regardless of an unparseable later source/condition dimension.
"""
import json
from chapter2_source_free_answer_scoring import source_free_requests,parse_source_free_judgments,COVERAGE_PROMPT,SOURCE_PROMPT
from chapter2_answer_scoring import metrics
from chapter2_segment_answer_scoring import segments

LATE_DIMENSION_ERRORS={'reasoning_condition_required','reasoning_audit_incomplete_actual_segments',
  'reasoning_audit_schema_invalid','reasoning_source_verdict_invalid','reasoning_condition_schema_invalid'}

def parse_partial_judgments(responses,payload,*,requests=None,strict_parser=None,rubric_version='source_free_v7'):
    requests=source_free_requests(payload) if requests is None else requests
    original=(parse_source_free_judgments if strict_parser is None else strict_parser)(responses,payload)
    if original['status']=='judged':return {**original,'rubric_version':rubric_version}
    if original.get('reason') not in LATE_DIMENSION_ERRORS:return original
    # The strict v6 parser reaches these errors only AFTER validating every
    # response/model/budget/request binding and every candidate-only point.
    actual={r['id']:r for r in segments(payload['answer'])}
    points=[];support={};mapping={'full':'satisfied','partial':'partial','missing':'omitted','wrong':'contradicted','unknown':'unknown'}
    for request,response in zip(requests[:-1],responses[:-1]):
        value=json.loads(response['response']['choices'][0]['message']['content']);ids=value['answer_segment_ids']
        support[request['point_id']]=[actual[v] for v in ids]
        points.append({'id':request['point_id'],'verdict':mapping[value['verdict']],
          'answer_quote':actual[ids[0]]['text'] if ids else '', 'reason':value['reason']})
    if not any(p['verdict'] in {'partial','omitted','contradicted'} for p in points):return original
    judgment={'points':points,'additional_claims':[], 'critical_errors':[],
      'factuality':{'verdict':'unknown','reason':'Later source audit not fully parseable; no factuality verdict recovered.'},
      'applicability':{'verdict':'unknown' if payload['rubric']['condition_discrimination'] else 'not_applicable',
        'reason':'Later dimension unknown; sealed nonconditional label remains not applicable.'}}
    m=metrics(judgment,payload['rubric']['required_points']);m.pop('critical_errors_triggered')
    assert m['complete_lower']==m['complete_upper']==0
    return {'status':'partially_judged','reason':original['reason'],'rubric_version':rubric_version,'judgment':judgment,
      'metrics':m,'actual_answer_support_segments':support,'critical_error_labels_assessed':False,
      'source_condition_dimensions_unknown':True,'fully_parsed_judgment':False,
      'derivation':'Every required point already parsed and grounded in actual candidate IDs. A known missing/partial/wrong point fixes complete=0; later unknown dimensions are retained, not repaired.'}
