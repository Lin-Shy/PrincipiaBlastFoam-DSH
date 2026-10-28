"""Correct only the 12 Top-5 8B requests missing baseline /no_think control.

Retain the confounded valid branch; never alter any original answer or label.
"""
from concurrent.futures import ThreadPoolExecutor,as_completed
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import single_pass_dev40 as s
import dev40_supplement as study

ROOT=study.ROOT/'single_pass_corrected'


def run():
    old=study.ROOT/'single_pass'
    packet=s.load(old/'scoring/packet.json')
    ROOT.mkdir(exist_ok=True)
    affected=[r for r in packet['items'] if r['model']=='qwen3-8b' and not (old/'generation'/('top5__'+r['model'])/r['qid']/'reuse.json').exists()]
    assert len(affected)==12
    protocol=dict(schema='dev40_single_pass_controlled_top5',scope=dict(generation_sessions=80),
        parent_protocol_sha256=s.sha(old/'protocol.json'),parent_study_protocol_sha256=s.sha(study.ROOT/'protocol.json'),
        correction='Add the original 8B last-user /no_think suffix; preserve all original wire parameters and baseline generation prompt',
        affected_question_ids=sorted(r['qid'] for r in affected),new_physical_generations=12,
        excluded_from_parameter_selection='The 12 prior 8B Top-5 requests omitted baseline nonthinking suffix and are retained as a confounded diagnostic',
        unaffected='56 exact input reuses and 12 valid 14B Top-5 generations/scores reused',
        source_sha256=s.sha(Path(__file__)),test160=False)
    p=ROOT/'protocol.json'
    if p.exists():assert s.load(p)==protocol
    else:s.save(p,protocol)
    questions={q['id']:q['question'] for q in s.load(s.QUESTIONS)}
    affected_ids={r['qid'] for r in affected}
    def job(row):
        model=row['model'];qid=row['qid'];source=old/'generation'/('top5__'+model)/qid
        target=ROOT/'generation'/('top5__'+model)/qid
        if (target/'result.json').exists():return 'existing'
        target.mkdir(parents=True,exist_ok=True)
        ret=s.load(source/'retrieval.json')
        s.save(target/'retrieval.json',ret)
        if model!='qwen3-8b' or qid not in affected_ids:
            s.save(target/'result.json',s.load(source/'result.json'))
            s.save(target/'reuse.json',dict(source=str(source),source_sha256=s.sha(source/'result.json'),exact_wire_input_equal=True))
            return 'reused'
        if (target/'requests').exists():return 'unknown_hold'
        baseline=study.original(model,qid)
        recorded=next((baseline/'model_requests').glob('*.json'))
        original_request=s.load(recorded)['request']
        assert original_request['messages'][-1]['content'].rstrip().endswith('/no_think')
        prompt='Question:\n'+questions[qid]+'\n\nRetrieved original-source evidence (JSON, including paths and line numbers):\n'+ret['delivery']+'\n\n'+s.load(s.OUT/'protocol.json')['generation_prompt']+'\n/no_think'
        body=deepcopy(original_request);body['messages']=[dict(role='user',content=prompt)]
        response=study.client(target,model)(body,0)
        raw=response.get('raw_response',{});answer=raw.get('choices',[{}])[0].get('message',{}).get('content') or ''
        success=response['status']=='response' and bool(answer) and raw['choices'][0]['finish_reason']=='stop'
        result=dict(config_id='top5__'+model,model=model,question_id=qid,answer=answer,
            status='success' if success else response['status'],generation_failed=not success,
            usage=raw.get('usage',{}),retrieval_characters=ret['delivered_characters'],
            protocol_sha256=s.sha(ROOT/'protocol.json'),corrected_nonthinking_control=True)
        s.save(target/'result.json',result)
        actual=s.load(target/'requests/00.request.json')['body']
        assert {k:v for k,v in actual.items() if k!='messages'}=={k:v for k,v in original_request.items() if k!='messages'}
        return dict(qid=qid,status=result['status'])
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures=[pool.submit(job,row) for row in packet['items']]
        for f in as_completed(futures):
            result=f.result()
            if isinstance(result,dict):print(json.dumps(result),flush=True)
    corrected=[]
    for row in packet['items']:
        target=ROOT/'generation'/('top5__'+row['model'])/row['qid']
        raw=s.load(target/'result.json');item=deepcopy(row['item'])
        reused=(target/'reuse.json').exists()
        if not reused:
            item['sample_id']='SP'+hashlib.sha256(('controlled_top5|'+row['qid']+'|'+s.sha(target/'result.json')).encode()).hexdigest()[:16]
            item['answer']=raw['answer'];item['generation_failed']=raw['generation_failed']
        corrected.append(dict(model=row['model'],method=row['method'],qid=row['qid'],item=item))
        if reused:
            for judge in s.JUDGES:
                source=old/'scoring'/judge/item['sample_id']/'parsed.json'
                if not source.exists():raise ValueError('Missing unaffected valid score')
                dest=ROOT/'scoring'/judge/item['sample_id']
                if not (dest/'parsed.json').exists():s.save(dest/'parsed.json',s.load(source))
                s.save(dest/'reuse.json',dict(source=str(source),sha256=s.sha(source),exact_input_equal=True))
    value=dict(count=80,items=corrected,protocol_sha256=s.sha(ROOT/'protocol.json'))
    if (ROOT/'scoring/packet.json').exists():assert s.load(ROOT/'scoring/packet.json')==value
    else:s.save(ROOT/'scoring/packet.json',value)
    s.save(study.ROOT/'transport_correction.json',dict(corrected_scope='single_pass_corrected',
        affected=protocol['affected_question_ids'],old_branch_retained=True,old_branch_8b_control_confounded=True,
        selection_source='single_pass_corrected; prior 8B new responses not used in primary comparison',
        actual_wire_checked=True,original_240_regenerated=0))


if __name__=='__main__':run()
