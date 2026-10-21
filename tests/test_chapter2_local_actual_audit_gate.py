import importlib.util
import json
from pathlib import Path
import sys
import pytest

SRC = Path(__file__).resolve().parents[1]/'experiments/retrieval_method'
sys.path.insert(0, str(SRC))
spec = importlib.util.spec_from_file_location('local_actual_audit', SRC/'chapter2_run_local_actual_audit.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


@pytest.mark.parametrize('report', [None, {'numeric_thresholds_passed':False,'overall':{'controls':42}},
                                   {'numeric_thresholds_passed':True,'overall':{'controls':18}}])
def test_incomplete_calibration_stops_before_client(tmp_path, monkeypatch, report):
    if report is not None:
        path = tmp_path/'development/local_score_calibration_004/report.json'
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(report), encoding='utf-8')
    def forbidden(*args, **kwargs):
        pytest.fail('Client constructed before calibration acceptance')
    monkeypatch.setattr(module, 'LocalQwenClient', forbidden)
    monkeypatch.setattr(sys, 'argv', ['audit','--activity',str(tmp_path),'--execute',
                                     '--settings',str(tmp_path/'absent-secret.env')])
    with pytest.raises((FileNotFoundError, ValueError)):
        module.main()
    assert not (tmp_path/'development/local_actual_answer_audit_004').exists()


def full_controls(root):
    def write(path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding='utf-8')
    cal = root/'development/local_score_calibration_004'
    controls = root/'development/score_controls_003/expected-controls.json'
    ids = ['control_'+str(i) for i in range(42)]
    write(controls, dict(controls=[dict(control_id=cid) for cid in ids]))
    registration = cal/'registration.json'
    write(registration, dict(inputs_sha256={str(controls):module.sha(controls)}))
    corpus = root/'corpus';corpus.mkdir()
    source = corpus/'source.txt';source.write_text('Original evidence\n', encoding='utf-8')
    span = dict(path='source.txt',sha256=module.sha(source),start=1,end=1,
                lines=[dict(number=1,text='Original evidence')])
    write(root/'development/formal_preparation_005/local-resources.json',dict(corpus=str(corpus)))
    rows=[];reviews=[]
    for cid in ids:
        folder=cal/'sessions'/cid
        write(folder/'score.json',dict(control_id=cid))
        write(folder/'requests/00.json',dict(request=dict(messages=[dict(content=json.dumps(
              dict(original_material={'source':span}))+'\n/no_think')])) )
        rows.append(dict(control_id=cid,score_file_sha256=module.sha(folder/'score.json')))
        reviews.append(dict(control_id=cid,changes_to_automatic_score=False,
            score_sha256=module.sha(folder/'score.json'),request_sha256={'00.json':module.sha(folder/'requests/00.json')},
            originals=[{k:span[k] for k in ('path','sha256','start','end')}]))
    write(cal/'report.json',dict(numeric_thresholds_passed=True,overall=dict(controls=42),
                               registration_sha256=module.sha(registration),rows=rows))
    write(cal/'semantic-review-batch-001.json',dict(candidate='compact_local_004',human_truth=False,rows=reviews))
    inventory={str(p.relative_to(cal)):module.sha(p) for p in cal.rglob('*.json') if 'semantic-review' not in p.name}
    write(root/'audit/local_qwen_transition_001/local_calibration004_native_terminal.json',
          dict(native_returncode=0,completed_controls=42,report_sha256=module.sha(cal/'report.json'),files_sha256=inventory))
    return source, cal


def test_full_control_gate_rechecks_original_source(tmp_path):
    source, cal = full_controls(tmp_path)
    assert module.validate_controls(tmp_path)
    source.write_text('Changed evidence\n',encoding='utf-8')
    with pytest.raises(ValueError,match='Reviewed original source drift'):
        module.validate_controls(tmp_path)


def test_full_control_gate_rejects_missing_review(tmp_path):
    source, cal = full_controls(tmp_path)
    path=cal/'semantic-review-batch-001.json'
    value=json.loads(path.read_text(encoding='utf-8'));value['rows'].pop()
    path.write_text(json.dumps(value),encoding='utf-8')
    with pytest.raises(ValueError,match='All 42 original-source reviews'):
        module.validate_controls(tmp_path)


def test_transport_unknown_uses_only_bound_planned_source(tmp_path):
    def write(path,value):
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(value),encoding='utf-8')
    cal=tmp_path/'development/local_score_calibration_004';cid='interrupted'
    failure=cal/'sessions'/cid/'requests/00.json'
    write(failure,dict(status='transport_error',request=dict(messages=[dict(content='{}\n/no_think')])))
    write(cal/'sessions'/cid/'score.json',dict(status='judge_unknown',reason='preserved_local_transport_timeout',
          metrics=dict(complete_valid_answer=None,complete_lower=0,complete_upper=1),unattempted_stage_indices=[1]))
    write(tmp_path/'audit/local_qwen_transition_001/compact_calibration_timeout_terminal.json',
          dict(failed_request=failure.relative_to(cal).as_posix(),failed_request_sha256=module.sha(failure)))
    prior=tmp_path/'old/sessions/case/score.json'
    write(prior,dict(result_relative_path='sessions/'+cid+'/result.json'))
    write(prior.parent/'requests/00.json',dict(request=dict(messages=[dict(content='{}')])))
    planned=prior.parent/'requests/01.json'
    write(planned,dict(request=dict(messages=[dict(content=json.dumps(dict(original_material={'source':'bound'})))])))
    row=dict(control_id=cid,model_judgments_available=False,planned_audit_request=str(planned.relative_to(tmp_path)),
             planned_audit_request_sha256=module.sha(planned))
    registered=dict(inputs_sha256={str(planned):module.sha(planned),str(prior):module.sha(prior)})
    assert module.review_audit_input(tmp_path,cal,row,[failure],registered)['original_material']=={'source':'bound'}
    row['model_judgments_available']=True
    with pytest.raises(ValueError,match='bound transport unknown'):
        module.review_audit_input(tmp_path,cal,row,[failure],registered)
    row['model_judgments_available']=False;row['planned_audit_request_sha256']='0'*64
    with pytest.raises(ValueError,match='planned source drift'):
        module.review_audit_input(tmp_path,cal,row,[failure],registered)
