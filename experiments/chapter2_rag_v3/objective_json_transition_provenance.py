"""Bind the complete transition archive without publishing private requests."""
import hashlib
import json
from pathlib import Path
import objective_experiment as exp
import objective_json_transition as transition


def main():
    out = transition.OUT
    snap = out/'results/snapshot.json'; audit = exp.read(out/'results/json_audit.json')
    if audit['status'] != 'passed' or audit['snapshot_sha256'] != exp.sha(snap):
        raise ValueError('Matching closed audit required')
    manifest = exp.read(out/'manifest.json')
    public = {k:v for k,v in manifest.items() if k != 'deployments'}
    public['configurations'] = [{k:v for k,v in c.items() if k != 'endpoint'} for c in manifest['configurations']]
    public['deployments'] = {k:{'source':v.get('source'), 'endpoint_sha256':hashlib.sha256(v['endpoint'].encode()).hexdigest()}
                             for k,v in manifest['deployments'].items()}
    exp.save(out/'manifest_public.json', public)
    inventory = out/'results/raw_inventory.jsonl'; count = 0
    with inventory.open('w', encoding='utf8', newline='\n') as f:
        for root in (transition.OLD, out):
            for path in sorted(p for p in (root/'generation').rglob('*') if p.is_file()):
                item = dict(path=str(path.relative_to(exp.BASE)).replace('\\','/'),
                            sha256=exp.sha(path), bytes=path.stat().st_size)
                f.write(json.dumps(item,ensure_ascii=False,sort_keys=True)+'\n'); count += 1
    outputs = ['results/snapshot.json','results/per_answer.csv','results/summary.csv','scores/per_answer.json',
               'results/index.html','results/json_audit.json','results/raw_inventory.jsonl',
               'reuse_inventory.json','unknown_inventory.json','unstarted_inventory.json','manifest_public.json',
               'analysis/capability_labels_v2.json','analysis/thesis_audit.json',
               'results/publish_provenance.json','results/sync_provenance.json','results/transition_publish_provenance.json']
    exp.save(out/'results/provenance.json', dict(schema='objective-json-transition-provenance-v1',
        manifest_sha256=exp.sha(out/'manifest.json'), parent_manifest_sha256=exp.sha(transition.OLD/'manifest.json'),
        raw_file_count=count, outputs={p:exp.sha(out/p) for p in outputs},
        code_sha256=exp.sha(Path(__file__)), note='Private request bodies and endpoints remain local; inventory contains hashes and relative paths only.'))
    print('Transition provenance bound:',count,'files')


if __name__ == '__main__': main()
