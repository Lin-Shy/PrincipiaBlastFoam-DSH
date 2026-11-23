"""Offline integrity/configuration checks; not an OS or cluster isolation test."""
import hashlib
import json
from pathlib import Path
import sys
import yaml

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def verify(pair):
    manifest=json.loads((pair/'manifest.json').read_text(encoding='utf-8'))
    changed=[p for p,h in manifest['source_sha256'].items() if sha(Path(p))!=h]
    assert not changed, changed
    assert not any(getattr(p.lstat(),'st_file_attributes',0)&1024 or p.is_symlink() for p in pair.rglob('*'))
    seen=set()
    for arm in ['general','professional']:
        root=pair/arm
        entries=yaml.load((root/'dump.yml').read_text(encoding='utf-8'),Loader=yaml.BaseLoader)
        by_id={x['id']:x for x in entries if 'id' in x}
        for key in ['agent-instructions','llm-deepseek','llm-pi-ai','session-title-llm']:
            assert str(by_id[key]['disabled']).lower()=='true',key
        config=by_id['skill-filesystem']['config']
        assert str(config['includeDefaultRoots']).lower()=='false'
        assert config['customSkillDirs']==[] and Path(config['bundledSkillDir']).resolve()==(root/'skills').resolve()
        assert 'principia' not in (root/'dump.yml').read_text(encoding='utf-8').lower()
        for name in ['home','workspace','tmp','cache','agents_home','skills']:
            value=(root/name).resolve();assert value not in seen;seen.add(value)
    for relative in ['common/cluster_job.py','OPERATIONS.md','raw_sources.json']:
        assert sha(pair/'general/workspace'/relative)==sha(pair/'professional/workspace'/relative)
    task_files=list((pair/'public_task').rglob('*'))
    for source in task_files:
        if source.is_file():
            for arm in ['general','professional']:
                assert sha(source)==sha(pair/arm/'workspace/task'/source.relative_to(pair/'public_task'))
    return {'source_pins_verified':len(manifest['source_sha256']),'distinct_local_directories':len(seen),
            'no_reparse_paths':True,'common_task_and_bridge_equal':True,'providers_disabled':True,
            'os_isolation_verified':False,'remote_acceptance_verified':False}
if __name__=='__main__':print(json.dumps(verify(Path(sys.argv[1]).resolve()),indent=2))
