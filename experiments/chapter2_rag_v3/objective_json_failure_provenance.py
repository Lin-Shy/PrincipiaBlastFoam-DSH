"""Hash the post-hoc recovery and both parent raw archives without secrets."""
import hashlib
import json
from pathlib import Path
import objective_experiment as exp
import objective_json_failure_rerun as run
import objective_json_transition as transition


def main():
    out=run.OUT;snap=out/'results/snapshot.json';audit=exp.read(out/'results/json_audit.json')
    if audit['status']!='passed' or audit['snapshot_sha256']!=exp.sha(snap):raise ValueError('Matching audit required')
    m=exp.read(out/'manifest.json');public={k:v for k,v in m.items() if k!='deployments'}
    public['configurations']=[{k:v for k,v in c.items() if k!='endpoint'} for c in m['configurations']]
    public['deployments']={k:dict(source=v.get('source'),endpoint_sha256=hashlib.sha256(v['endpoint'].encode()).hexdigest()) for k,v in m['deployments'].items()}
    exp.save(out/'manifest_public.json',public)
    inventory=out/'results/raw_inventory.jsonl';count=0
    with inventory.open('w',encoding='utf8',newline='\n') as f:
        for root in (transition.OLD,run.PARENT,out):
            for p in sorted(x for x in (root/'generation').rglob('*') if x.is_file()):
                f.write(json.dumps(dict(path=str(p.relative_to(exp.BASE)).replace('\\','/'),sha256=exp.sha(p),bytes=p.stat().st_size),ensure_ascii=False,sort_keys=True)+'\n');count+=1
    names=['manifest_public.json','reuse_inventory.json','rerun_inventory.json','analysis/capability_labels_v2.json',
           'results/snapshot.json','results/per_answer.csv','results/summary.csv','results/index.html',
           'results/json_audit.json','scores/per_answer.json','results/raw_inventory.jsonl',
           'analysis/thesis_audit.json','results/publish_final.json']
    exp.save(out/'results/provenance.json',dict(schema='objective-failure-recovery-provenance-v1',manifest_sha256=exp.sha(out/'manifest.json'),
        parent_manifest_sha256=exp.sha(run.PARENT/'manifest.json'),raw_file_count=count,outputs={x:exp.sha(out/x) for x in names},
        code_sha256=exp.sha(Path(__file__)),note='Original and new requests remain local; only relative names, lengths and hashes are public.'))
    print('Failure recovery provenance bound:',count,'files')


if __name__=='__main__':main()
