"""开发候选：只约束既定裁判 JSON 结构，保留所有语义判决选项。"""
from copy import deepcopy
import json


def object_schema(properties):
    return dict(type='object',properties=properties,required=list(properties),additionalProperties=False)


def constrain_requests(requests):
    result=deepcopy(requests)
    for request in result:
        body=request['body']
        value=json.loads(body['messages'][-1]['content'])
        reason=dict(type='string',minLength=1)
        if request['stage']=='source_free_coverage':
            ids=[r['id'] for r in value['premise_segments']]
            items=dict(type='string',enum=ids) if ids else dict(type='string')
            schema=object_schema(dict(verdict=dict(type='string',enum=['full','partial','missing','wrong','unknown']),
                answer_segment_ids=dict(type='array',items=items,maxItems=len(ids)),reason=reason))
            name='candidate_coverage'
        elif request['stage']=='independent_original_truth_audit':
            ids=[r['id'] for r in value['candidate_segments']]
            if len(ids)!=len(set(ids)):raise ValueError('Duplicate candidate segment identities')
            segments=[object_schema(dict(id=dict(type='string',const=sid),
                verdict=dict(type='string',enum=['supported','contradicted','unknown','not_substantive']),reason=reason)) for sid in ids]
            conditions=['correct','incorrect','incomplete','unknown'] if value['condition_required'] else ['not_applicable']
            schema=object_schema(dict(segments=dict(type='array',prefixItems=segments,minItems=len(ids),maxItems=len(ids)),
                condition=object_schema(dict(verdict=dict(type='string',enum=conditions),reason=reason))))
            name='candidate_original_audit'
        else:raise ValueError('Unknown fixed judge stage')
        body['response_format']=dict(type='json_schema',json_schema=dict(name=name,strict=True,schema=schema))
    return result
