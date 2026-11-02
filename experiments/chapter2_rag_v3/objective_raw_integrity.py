"""Check every retained generation file against the closed raw inventory."""
import json
from pathlib import Path
import objective_experiment as exp

def main():
    out=exp.OUT;inventory=out/'results/raw_inventory.jsonl';provenance=exp.read(out/'results/provenance.json')
    if exp.sha(inventory)!=provenance['raw_inventory_sha256']:raise ValueError('inventory hash mismatch')
    count=0;errors=[];seen=set();root=out.resolve()
    with inventory.open(encoding='utf8') as handle:
        for line in handle:
            item=json.loads(line);path=(out/item['path']).resolve();count+=1
            if path in seen or not path.is_relative_to(root) or not path.is_file() or path.stat().st_size!=item['bytes'] or exp.sha(path)!=item['sha256']:
                errors.append(item['path'])
            seen.add(path)
    actual={p.resolve() for p in (out/'generation').rglob('*') if p.is_file()}
    if seen!=actual:errors.append('generation file set mismatch')
    if errors or count!=provenance['raw_file_count']:raise ValueError('raw inventory mismatch: '+str(errors[:5]))
    exp.save(out/'analysis/raw_integrity_audit.json',dict(status='passed',file_count=count,
        inventory_sha256=exp.sha(inventory),manifest_sha256=provenance['manifest_sha256'],
        method='Re-read every local raw file and compare SHA-256 and size to frozen inventory.',code_sha256=exp.sha(Path(__file__))))
    print('raw integrity audit passed:',count,'files')
if __name__=='__main__':main()
