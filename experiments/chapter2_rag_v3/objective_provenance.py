"""Bind closed objective outputs and original records without copying private requests."""
import hashlib
import json
from pathlib import Path
import objective_experiment as exp

def main():
    snapshot=exp.read(exp.OUT/'results/snapshot.json')
    supplement=exp.read(exp.OUT/'supplementary_parser/results/snapshot.json')
    if snapshot['status']!='closed' or supplement['status']!='closed':
        raise ValueError('closed scoring snapshots required')
    if supplement['source_strict_sha256']!=exp.sha(exp.OUT/'scores/per_answer.json'):
        raise ValueError('supplementary snapshot does not bind strict snapshot')
    raw=exp.OUT/'generation'
    entries=[]
    for path in sorted(p for p in raw.rglob('*') if p.is_file()):
        entries.append({'path':path.relative_to(exp.OUT).as_posix(),'sha256':exp.sha(path),'bytes':path.stat().st_size})
    target=exp.OUT/'results/raw_inventory.jsonl'
    target.write_text(''.join(json.dumps(x,ensure_ascii=False,sort_keys=True)+'\n' for x in entries),encoding='utf-8',newline='\n')
    here=Path(__file__).resolve().parent
    sources=['objective_experiment.py','objective_scoring.py','objective_statistics.py','objective_report.py',
             'objective_scoring_relaxed.py','objective_supplementary_report.py','objective_format_pairs.py',
             'objective_audit.py','objective_supplementary_audit.py','objective_assets.py','objective_manuscript.py',
             'objective_provenance.py']
    outputs=['results/snapshot.json','results/per_answer.csv','results/summary.csv','scores/per_answer.json',
             'results/closure_audit.json','supplementary_parser/results/snapshot.json',
             'supplementary_parser/results/per_answer.csv','supplementary_parser/results/summary.csv',
             'supplementary_parser/results/closure_audit.json','analysis/format_pairs.csv',
             'results/raw_inventory.jsonl']
    missing=[x for x in outputs if not (exp.OUT/x).is_file()]
    if missing:raise ValueError('missing outputs: '+str(missing))
    exp.save(exp.OUT/'results/provenance.json',{
        'schema':'objective-provenance-v1','manifest_sha256':exp.sha(exp.MANIFEST),
        'raw_file_count':len(entries),'raw_inventory_contains_file_contents':False,
        'raw_inventory_sha256':exp.sha(target),
        'source_sha256':{x:exp.sha(here/x) for x in sources},
        'output_sha256':{x:exp.sha(exp.OUT/x) for x in outputs},
        'note':'Original requests remain local; inventory binds their bytes without exposing endpoint or credentials.'})
    print('Provenance bound:',len(entries),'original files')

if __name__=='__main__':main()
