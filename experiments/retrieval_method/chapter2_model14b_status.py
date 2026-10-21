"""Current 14B progress from actual terminal records; never infer semantic success."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
from chapter2_optimization_200 import read, sha


def status(root, plan=None):
    protocol=read(root/'protocol.json')
    if protocol['answer_model']!='qwen3-14b' or protocol['generation_sessions']!=1400:
        raise ValueError('Wrong answer-model grid')
    generation=Counter()
    scoring=Counter()
    by_arm={}
    for arm in protocol['arms']:
        counts=Counter()
        for path in (root/'generation'/arm).glob('*/result.json'):
            try:
                result=read(path)
            except json.JSONDecodeError:
                continue
            if result['protocol_sha256']!=sha(root/'protocol.json'):
                raise ValueError('Generation identity drift')
            counts[result['status']]+=1
        by_arm[arm]=dict(registered=200,closed=sum(counts.values()),statuses=dict(counts))
        generation.update(counts)
    for path in (root/'scoring_001/sessions').glob('*/*/result.json'):
        try:
            result=read(path)
        except json.JSONDecodeError:
            continue
        scoring[result['status']]+=1
    if (root/'completion-pipeline-complete.json').exists():
        phase='generation_scoring_statistics_complete'
    elif (root/'scoring_001/completion.json').exists():
        phase='analysis_running'
    elif (root/'scoring_001/protocol.json').exists():
        phase='scoring_running'
    elif (root/'generation-controller-completion.json').exists():
        phase='generation_closed_audit_or_scoring_preparation'
    else:
        phase='generation_running'
    report=dict(updated_utc=datetime.now(timezone.utc).isoformat(),answer_model='qwen3-14b',
        phase=phase,registered=1400,closed=sum(generation.values()),
        valid_format_answers=generation.get('answered',0),
        generation_statuses=dict(generation),by_arm=by_arm,
        scores_closed=sum(scoring.values()),score_statuses=dict(scoring),
        protocol_sha256=sha(root/'protocol.json'),
        meaning='A valid final JSON is not a semantically correct answer; quality only after frozen scoring/analysis.')
    (root/'live-status.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    if plan:
        value=read(plan)
        complete=phase=='generation_scoring_statistics_complete'
        value['program_status']=('8b_14b_complete_32b_waiting_user_api' if complete
            else '14b_'+phase+'_32b_waiting_api')
        value['answer_model_matrix']['qwen3-14b'].update(
            status='complete' if complete else phase,generation_closed=report['closed'],valid_format_answers=report['valid_format_answers'],
            score_sessions_closed=report['scores_closed'],progress_file=root.name+'/live-status.json')
        plan.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='by_arm'},ensure_ascii=False))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,required=True);p.add_argument('--plan',type=Path)
    args=p.parse_args();status(args.root,args.plan)
