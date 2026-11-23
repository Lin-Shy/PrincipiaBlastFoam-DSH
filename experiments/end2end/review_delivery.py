"""Independent delivery inventory and raw-pressure recomputation, no solver.

This prepares evidence for six-dimensional review; file existence and numeric
recomputation cannot certify physical conditions, execution, or prediction accuracy.
"""
import argparse
import hashlib
import json
from pathlib import Path
from pressure_observations import read_scalar_probes,window,metrics

def inspect(task,delivery):
    task=Path(task);delivery=Path(delivery).resolve()
    conditions=json.loads((task/'conditions.json').read_text(encoding='utf-8'))
    required=[f'R{round(r*1000):04d}' for r in conditions['probe_radii_m']] if 'probe_radii_m' in conditions else [f'P{i+1}' for i in range(len(conditions['probe_locations_m']))]
    ambient=conditions.get('ambient_pa',conditions.get('ambient',{}).get('pressure_absolute_Pa'))
    if ambient is None:raise ValueError('task pressure baseline missing')
    start,end=conditions['metric_window_s']
    inventory=[]
    for file in sorted(delivery.rglob('*')):
        if file.is_symlink() or getattr(file.lstat(),'st_file_attributes',0)&1024:raise ValueError('delivery links require separate review, not followed')
        if file.is_file():
            h=hashlib.sha256()
            with file.open('rb') as f:
                for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
            inventory.append({'path':file.relative_to(delivery).as_posix(),'bytes':file.stat().st_size,'sha256':h.hexdigest()})
    observations=delivery/'observations.json';recomputed=[];issues=[]
    if not observations.exists():issues.append('observations.json missing; raw-data mapping unavailable')
    else:
        mapping=json.loads(observations.read_text(encoding='utf-8'))
        if sorted(r['sensor_id'] for r in mapping['records'])!=sorted(required):issues.append('sensor identity/count mismatch')
        for item in mapping['records']:
            raw=(delivery/item['raw_file']).resolve()
            if not raw.is_relative_to(delivery):raise ValueError('raw file outside delivery')
            try:
                rows=read_scalar_probes(raw)
                all_metrics=metrics(window(rows,start,end),ambient_pa=ambient,pressure_unit='Pa')
                column=item['column']
                if type(column)!=int or not 0<=column<len(all_metrics):raise ValueError('invalid raw pressure column')
                recomputed.append({'sensor_id':item['sensor_id'],'raw_file':item['raw_file'],'column':column,'metrics':all_metrics[column]})
            except (ValueError,OSError) as error:issues.append({'sensor_id':item['sensor_id'],'raw_data_error':str(error)})
    return {'inventory':inventory,'raw_recomputed_metrics':recomputed,'issues':issues,
        'raw_window_complete':not issues and len(recomputed)==len(required),
        'conditions':'pending_external_review','computation':'pending_scheduler_and_raw_state_review',
        'data_delivery':'partial_evidence_only; compare recomputation with delivered CSV/metrics/figure and sensor positions',
        'reproducibility':'pending_package_review; independent_rerun_not_performed',
        'reliability':'requires_attempt_population','total_cost':'join_operator_ledgers',
        'engineering_delivery_complete':None,'prediction_accuracy':'pending'}

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--task',type=Path,required=True);p.add_argument('--delivery',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    result=inspect(a.task,a.delivery)
    with a.output.open('x',encoding='utf-8') as f:json.dump(result,f,ensure_ascii=False,indent=2)
