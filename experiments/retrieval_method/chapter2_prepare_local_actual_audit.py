"""绑定既有15份方法遮蔽开发回答，准备紧凑本地裁判盲审；不调用模型。"""
import argparse,hashlib,json,sys
from pathlib import Path
from chapter2_qwen_local import LocalModel,prepare_body
from chapter2_qwen_compact_grammar import compact_grammar_requests

def read(p):return json.loads(p.read_text(encoding='utf-8'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def bodysha(body):return hashlib.sha256(json.dumps(body,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--activity',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();root=a.activity.resolve()
    if a.output.exists():raise FileExistsError(a.output)
    pack=root/'development/actual_answer_review_001';old=root/'development/actual_answer_scoring_001'
    selection=read(pack/'selection.json');source=pack/'evaluation_only/inputs.json';inputs=read(source)
    if sha(source)!=selection['inputs_sha256'] or sha(pack/'evaluation_only/blind-key.json')!=selection['blind_key_sha256']:
        raise ValueError('Original blinded selection drift')
    if len(inputs)!=15 or len({r['review_id'] for r in inputs})!=15 or len({r['question_id'] for r in inputs})!=15:
        raise ValueError('All fixed fifteen questions required')
    if selection['questions']!=15 or selection['themes']!=15 or set(selection['method_counts'].values())!={3}:
        raise ValueError('Original balanced scope drift')
    verdictpath=pack/'evaluation_only/codex-verdicts.json';verdicts=read(verdictpath)
    if verdicts['input_pack_sha256']!=sha(source) or verdicts['human_truth'] is not False:
        raise ValueError('Original source opinions bind another input pack')
    protocol=read(old/'protocol.json')
    if protocol['rubric_version']!='source_free_v7':raise ValueError('Only the accepted original v7 input definition is reused')
    for name,value in protocol['source_sha256'].items():
        if sha(old/'runtime'/name)!=value:raise ValueError('Original judge input generator drift')
    sys.path.insert(0,str(old/'runtime/src'));sys.path.insert(0,str(old/'runtime/experiments/retrieval_method'))
    from chapter2_partial_answer_scoring import source_free_requests
    deployment_registration=root/'development/local_score_calibration_004/registration.json'
    deployment=read(deployment_registration)
    local=LocalModel(deployment['endpoint'],deployment['model'],'not-loaded')
    by_qid={read(f)['question_id']:f for f in old.glob('sessions/*/score.json')}
    if set(by_qid)!={r['question_id'] for r in inputs}:raise ValueError('Prior actual-answer input coverage differs')
    bindings={str(f.relative_to(root)):sha(f) for f in [source,pack/'selection.json',verdictpath,
        pack/'judge-input-bindings.json',old/'protocol.json',deployment_registration]}
    rows=[]
    for row in inputs:
        scorefile=by_qid[row['question_id']];score=read(scorefile)
        resultpath=pack/'generation'/score['result_relative_path'];result=read(resultpath)
        if sha(resultpath)!=score['result_sha256'] or protocol['result_bindings'][score['result_relative_path']]!=sha(resultpath):
            raise ValueError('Actual answer result drift')
        if result['answer']!=row['answer'] or result['status']!=row['generation_status']:
            raise ValueError('Masked pack and original result differ')
        payload={key:row[key] for key in ['question','answer','rubric','original_material']}
        requests=source_free_requests(payload) if result['status']=='answered' else []
        files=sorted((scorefile.parent/'requests').glob('*.json'))
        if [read(f)['request'] for f in files]!=[r['body'] for r in requests]:
            raise ValueError('Masked original request reconstruction mismatch')
        transformed=compact_grammar_requests(requests)
        for f in [resultpath,scorefile,*files]:bindings[str(f.relative_to(root))]=sha(f)
        rows.append(dict(review_id=row['review_id'],question_id=row['question_id'],
            result_relative_path=str(resultpath.relative_to(root)),result_sha256=sha(resultpath),
            generation_status=result['status'],planned_requests=len(requests),
            actual_request_sha256=[bodysha(prepare_body(r['body'],local)) for r in transformed]))
    report=dict(schema='compact_local_actual_development_audit_preparation_v1',formal_result=False,human_truth=False,
        planned_answers=15,planned_themes=15,selection_changed=False,method_key_decoded=False,
        copied_method_labels_into_requests=False,model_calls=0,credentials_loaded=False,rows=rows,
        judge_transform='candidate_segments_compact_grammar_hard_nonthinking_v1',inputs_sha256=bindings,
        pre_execution_requires=['full compact calibration native terminal','original numeric thresholds passed','all 42 control source reviews bound'],
        final_admission_requires='all 15 actual answers scored and personally reviewed; retain all disagreements and unknowns',
        implementation_sha256=sha(Path(__file__)))
    a.output.parent.mkdir(parents=True,exist_ok=True)
    with a.output.open('x',encoding='utf-8') as f:json.dump(report,f,ensure_ascii=False,indent=2)
    print(json.dumps(dict(answers=len(rows),requests=sum(r['planned_requests'] for r in rows),model_calls=0)))

if __name__=='__main__':main()
