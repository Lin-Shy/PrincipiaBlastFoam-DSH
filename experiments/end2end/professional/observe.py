"""Domain CLI: reuse native-pressure analysis without asserting simulation success."""
import argparse
import hashlib
import json
import math
from pathlib import Path
from pressure_observations import read_scalar_probes, window, metrics

def analyze(path,ambient,start,end):
    if not all(math.isfinite(v) for v in (ambient,start,end)) or start>=end:
        raise ValueError('finite ambient and increasing time window required')
    rows=read_scalar_probes(path)
    result={'source_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'available_window_s':[rows[0][0],rows[-1][0]],
            'requested_window_s':[start,end],'ambient_pa':ambient,'scientific_accuracy':'not_assessed'}
    if rows[0][0]>start or rows[-1][0]<end:
        result.update(status='incomplete_window',metrics=None)
    else:
        result.update(status='computed',metrics=metrics(window(rows,start,end),ambient_pa=ambient,pressure_unit='Pa'))
    return result

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('raw',type=Path);p.add_argument('--ambient-pa',type=float,required=True)
    p.add_argument('--start',type=float,required=True);p.add_argument('--end',type=float,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    result=analyze(a.raw,a.ambient_pa,a.start,a.end)
    with a.output.open('x',encoding='utf-8') as f:json.dump(result,f,indent=2)
if __name__=='__main__':main()
