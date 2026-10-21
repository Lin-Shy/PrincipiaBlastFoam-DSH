"""Offline recovery rehearsal on a temporary copy; stop before the first fresh request."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys
import tempfile
import chapter2_resume_local_compact_calibration as resume
from chapter2_qwen_local import LocalModel


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--activity',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();root=args.activity.resolve()
    if args.output.exists():raise FileExistsError(args.output)
    source=root/'development/local_score_calibration_004'
    registration=resume.read(source/'registration.json')
    stop=resume.read(root/'audit/local_qwen_transition_001/compact_calibration_timeout_terminal.json')
    before={str(p.relative_to(source)):resume.sha(p) for p in source.rglob('*.json')}
    resources=resume.read(root/'development/formal_preparation_005/local-resources.json')
    dataset=Path(resources['questions']).parents[1]
    intercepted=[]
    class StopBeforeFreshRequest(Exception):pass
    class OfflineClient:
        def __init__(self,*args,**kwargs):
            self.deployment=LocalModel(registration['endpoint'],registration['model'],'not-loaded')
        def __call__(self,body,index):
            intercepted.append(dict(control_id=self.folder.parent.name,stage=index,body=body))
            raise StopBeforeFreshRequest()
    with tempfile.TemporaryDirectory(prefix='compact-resume-rehearsal-') as tmp:
        tmp=Path(tmp);copy=tmp/'calibration';shutil.copytree(source,copy)
        # Synthetic receipt exists only inside the temporary offline fixture.
        receipt=tmp/'synthetic-offline-receipt.json'
        resume.save(receipt,dict(provider='qwen_local',status='response',endpoint=registration['endpoint'],
             raw_response=dict(model=registration['model']),started_utc=datetime.now(timezone.utc).isoformat(),
             synthetic_offline_test_only=True))
        original_client=resume.LocalQwenClient;original_argv=sys.argv
        resume.LocalQwenClient=OfflineClient
        sys.argv=['resume','--activity',str(root),'--dataset',str(dataset),'--output',str(copy),
                  '--recovery-receipt',str(receipt)]
        try:
            try:resume.main()
            except StopBeforeFreshRequest:pass
            else:raise AssertionError('Recovery did not reach the expected fresh request boundary')
        finally:
            resume.LocalQwenClient=original_client;sys.argv=original_argv
        if len(intercepted)!=1 or intercepted[0]['control_id']!='P04-03_positive' or intercepted[0]['stage']!=0:
            raise AssertionError('Recovery would reissue a failed or completed stage')
        for name,value in before.items():
            if resume.sha(copy/name)!=value:raise AssertionError('Recovery modified a prior artifact')
        unknown=resume.read(copy/'sessions/P04-03_omission/score.json')
        if (unknown['status']!='judge_unknown' or unknown['metrics']!=dict(complete_valid_answer=None,
                complete_lower=0,complete_upper=1) or unknown['unattempted_stage_indices']!=[1,2,3]):
            raise AssertionError('Interrupted control unknown policy drift')
        if unknown['request_bindings']!={'0':stop['failed_request_sha256']}:
            raise AssertionError('Interrupted control lost original failed request binding')
        if len(list((copy/'sessions/P04-03_omission/requests').glob('*.json')))!=1:
            raise AssertionError('Later interrupted stages were issued')
    after={str(p.relative_to(source)):resume.sha(p) for p in source.rglob('*.json')}
    if before!=after:raise AssertionError('Offline rehearsal changed live calibration')
    report=dict(schema='compact_timeout_recovery_offline_rehearsal_v1',synthetic_fixture=True,
        actual_model_calls=0,credentials_loaded=False,live_calibration_unchanged=True,
        preserved_artifacts=len(before),completed_controls_reused=37,
        interrupted_control='P04-03_omission',interrupted_control_retained_unknown=True,
        unattempted_interrupted_stages=[1,2,3],first_fresh_control='P04-03_positive',
        failed_request_reissued=False,recovery_availability_proven=False,
        registration_sha256=resume.sha(source/'registration.json'),
        implementation_sha256=resume.sha(Path(__file__)),resume_implementation_sha256=resume.sha(Path(resume.__file__)))
    resume.save(args.output,report)
    print(json.dumps(report))


if __name__=='__main__':main()
