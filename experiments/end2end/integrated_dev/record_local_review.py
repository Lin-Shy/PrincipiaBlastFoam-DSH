"""Record post-seal assessor decisions. No submission is edited or regenerated."""
import argparse
import json
from local_sealed_tables import inspect
from b11_live import batch
from local_first_wave import update

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('task')
    for name in ['general','professional']:
        parser.add_argument('--'+name,nargs=4,metavar=('OVERALL','RUN','DIMENSIONS','COMMENT'))
    a=parser.parse_args()
    if not (a.general or a.professional):
        parser.error('specify at least one sealed arm')
    inspect(a.task)
    tables=json.loads((batch/'local_reviews'/a.task/'tables.json').read_bytes())
    for arm in ['general','professional']:
        if getattr(a,arm) is None:
            continue
        overall,run,dims,comment=getattr(a,arm)
        facts=tables['arms'][arm];f=batch/'attempts'/arm/a.task/'first'
        card=json.loads((f/'scorecard.json').read_bytes());status=json.loads((f/'status.json').read_bytes())
        assert status['run_evidence'] and len(dims)==4 and not card['reviewer']
        card.update(submission_manifest=status['run_evidence'],overall=overall,run_status=run,
            reviewer='操作者在双臂封存后按题卡独立核验',human_minutes=0,costs=json.loads((f/'cost.json').read_bytes()))
        ev=[status['run_evidence'],f'local_reviews/{a.task}/tables.json']
        if status['submission']:ev.append(status['submission'])
        for k,flag in zip(['工程与运行','变更或创建','目标输出','追溯'],dims):
            card['dimensions'][k]=dict(verdict={'Y':'通过','N':'未达到','?':'依据不足'}[flag],evidence=ev,reason=comment)
        card['dimensions']['人工补做']=dict(verdict='通过',evidence=ev,reason='首次封存前无人工补关键步骤；复核不回填交件。')
        card['dimensions']['数值精度']=dict(verdict='不适用',evidence=ev,reason='数字读出复算单列；未要求CFD、无独立实测。')
        card['review_summary']=comment
        update(f/'scorecard.json',card)
        status['verdict']=overall
        update(f/'status.json',status)
