"""用已完成开发响应离线验证正式执行核；不发请求、不改变评分。"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
from chapter2_local_structured_score_execution import score_local_answer,request_sha
from chapter2_qwen_local import LocalModel,prepare_body
from chapter2_qwen_structured_output import constrain_requests

def read(p):return json.loads(p.read_text(encoding='utf-8'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--activity',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();root=a.activity.resolve()
    if a.output.exists():raise FileExistsError(a.output)
    current=root/'development/local_score_calibration_002'
    old=root/'development/score_calibration_011'
    controls=root/'development/score_controls_003'
    registration=read(current/'registration.json')
    runtime=root/'setup/formal_evaluation_007/runtime'
    setup=read(root/'setup/formal_evaluation_007/evaluation.json')
    for name,value in setup['runtime_source_sha256'].items():
        if sha(runtime/name)!=value:raise ValueError('Frozen runtime drift')
    sys.path.insert(0,str(runtime/'src'));sys.path.insert(0,str(runtime/'experiments/retrieval_method'))
    import chapter2_reasoning_answer_scoring as reasoning
    import chapter2_partial_answer_scoring as partial
    from transformers import AutoTokenizer
    resources=read(root/'development/formal_preparation_005/local-resources.json')
    tokenfolder=Path(resources['tokenizer_qwen3-14b'])
    for name,value in read(tokenfolder/'artifact-binding.json')['files'].items():
        if sha(tokenfolder/name)!=value:raise ValueError('Frozen tokenizer drift')
    tokenizer=AutoTokenizer.from_pretrained(str(tokenfolder),local_files_only=True)
    count=lambda messages:len(tokenizer.apply_chat_template(messages,tokenize=True,add_generation_prompt=True,enable_thinking=True))
    dataset=Path(resources['questions']).parents[1]
    annotations={r['id']:r for r in read(dataset/'scoring/annotations.json')}
    by_control={Path(read(f)['result_relative_path']).parent.name:f for f in old.glob('sessions/*/score.json')}
    scorefiles=sorted(current.glob('sessions/*/score.json'))
    if not scorefiles:raise ValueError('No completed development response to replay')
    rows=[]
    for scorefile in scorefiles:
        cid=scorefile.parent.name;score=read(scorefile);prior=by_control[cid]
        oldrequests=[read(f)['request'] for f in sorted((prior.parent/'requests').glob('*.json'))]
        audit=json.loads(oldrequests[-1]['messages'][-1]['content'])
        resultpath=controls/'generation/sessions'/cid/'result.json'
        if registration['inputs_sha256'].get(str(resultpath))!=sha(resultpath):raise ValueError('Control drift')
        result=read(resultpath);ann=annotations[read(prior)['question_id']]
        payload=dict(answer=result['answer'],question=audit['question'],original_material=audit['original_material'],
            rubric=dict(required_points=ann['required_points'],condition_discrimination=ann['labels']['condition_discrimination'],applicability=ann['applicability']))
        reasoning.JUDGE_MODEL='qwen3-14b'
        from chapter2_source_free_answer_scoring import source_free_requests
        requests=source_free_requests(payload)
        if [r['body'] for r in requests]!=oldrequests:raise ValueError('Original request reconstruction mismatch')
        requests=constrain_requests(requests)
        requestfiles=sorted((scorefile.parent/'requests').glob('*.json'))
        records=[read(f) for f in requestfiles]
        if len(records)!=len(requests):raise ValueError('Completed score has missing requests')
        for i,f in enumerate(requestfiles):
            if score['request_bindings'][str(i)]!=sha(f):raise ValueError('Local development response drift')
        class Replay:
            deployment=LocalModel(registration['endpoint'],registration['model'],'not-loaded')
            calls=0
            def __call__(self,body,index):
                self.calls+=1
                if prepare_body(body,self.deployment)!=records[index]['request']:raise ValueError('Replay body mismatch')
                return records[index]
        client=Replay();actual=[prepare_body(r['body'],client.deployment) for r in requests]
        budget=dict(actual_input_tokens=[count(b['messages']) for b in actual],
            actual_request_sha256=[request_sha(b) for b in actual],local_context_limit=16384,
            response_schema_policy='candidate_segments_json_schema_v1')
        reasoning.JUDGE_MODEL=registration['model']
        def parse(rs,value,actual_requests):
            partial.source_free_requests=lambda ignored:actual_requests
            partial.parse_source_free_judgments=lambda responses,payload:reasoning.parse_reasoning_judgments(responses,payload,requests=actual_requests)
            return partial.parse_partial_judgments(rs,value)
        replayed=score_local_answer(result,payload,requests,client,budget,count,parse)
        if replayed['status']!=score['status']:raise ValueError('Execution kernel changed parser status')
        for key in ['judgment','metrics','actual_answer_support_segments','reason']:
            if key in score and score[key]!=replayed.get(key):raise ValueError('Execution kernel changed semantic score')
        if replayed['status']=='judge_unknown' and replayed['metrics']!={'complete_valid_answer':None,'complete_lower':0,'complete_upper':1}:
            raise ValueError('Unknown bounds drift')
        rows.append(dict(control_id=cid,score_sha256=sha(scorefile),response_files=len(records),
            replay_calls=client.calls,original_semantics_preserved=True))
    report=dict(schema='local_execution_real_response_replay_v1',controls=len(rows),
        frozen_evaluation_sha256=sha(root/'setup/formal_evaluation_007/evaluation.json'),
        local_registration_sha256=sha(current/'registration.json'),rows=rows,
        network_requests=0,credential_reads=0,complete_calibration_acceptance=False,
        implementation_sha256=sha(Path(__file__)),kernel_sha256=sha(Path(__file__).with_name('chapter2_local_structured_score_execution.py')))
    a.output.parent.mkdir(parents=True,exist_ok=True)
    with a.output.open('x',encoding='utf-8') as f:json.dump(report,f,indent=2)
    print(json.dumps(dict(controls=len(rows),response_files=sum(r['response_files'] for r in rows),semantics_preserved=True,network_requests=0)))

if __name__=='__main__':main()
