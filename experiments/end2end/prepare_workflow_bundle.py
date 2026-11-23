"""Copy the stdlib-only offline prototype and explicit inputs; no shared installs."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

PROJECT=Path(__file__).resolve().parents[2]
ARCHIVE=PROJECT.parent/'graduation-experiment-results/chapter3_end_to_end_evaluation'

RUNNER = '''import hashlib,json,sys
from pathlib import Path
root=Path(__file__).resolve().parent
manifest_path=root/'manifest.json'
if hashlib.sha256(manifest_path.read_bytes()).hexdigest()!=sys.argv[1]:raise ValueError('Manifest differs from parent pin')
manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
def verify():
 for folder in ['code','inputs']:
  for p in (root/folder).rglob('*'):
   if p.is_file() and p.relative_to(root).as_posix() not in manifest['payload_sha256']:raise ValueError('Untracked payload file')
 for relative,expected in manifest['payload_sha256'].items():
  p=(root/relative).resolve()
  if not p.is_relative_to(root) or hashlib.sha256(p.read_bytes()).hexdigest()!=expected:raise ValueError('Payload drift or escape')
 for p in root.rglob('*'):
  if getattr(p.lstat(),'st_file_attributes',0)&1024 or p.is_symlink():raise ValueError('Reparse point not allowed')
verify()
sys.path.insert(0,str(root/'code'))
import goal_observation_workflow as implementation
assert Path(implementation.__file__).resolve().is_relative_to(root/'code')
result={'isolated_flag':sys.flags.isolated,'no_site_flag':sys.flags.no_site,'module_origin':str(Path(implementation.__file__).relative_to(root)),'scenes':{}}
for sid in manifest['scenes']:
 inputs=root/'inputs'/sid
 task=json.loads((inputs/'task.json').read_text(encoding='utf-8'))
 query=json.loads((inputs/'analysis_requests.json').read_text(encoding='utf-8'))[0]
 source=inputs/'p'
 workflow=implementation.Workflow(inputs,root/'outputs'/sid,cache=True,goal_state=True,final_check=True)
 value=workflow.run(task,query,source,manifest['payload_sha256']['inputs/'+sid+'/p'])
 result['scenes'][sid]={'claims':value['claims'],'check':value['check']}
verify()
(root/'validation.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps({'isolated':sys.flags.isolated,'no_site':sys.flags.no_site,'scenes':list(result['scenes'])}))
'''


def prepare(replay,destination):
    replay,destination=replay.resolve(),destination.resolve()
    if not replay.is_relative_to(ARCHIVE.resolve()) or not destination.is_relative_to(ARCHIVE.resolve()):
        raise ValueError('Inputs and output must remain in Chapter 3 archive')
    destination.mkdir(parents=True,exist_ok=False)
    payload={}
    original_pins={}
    def copy(original,relative):
        before=hashlib.sha256(original.read_bytes()).hexdigest()
        target=destination/relative;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(original,target)
        if hashlib.sha256(target.read_bytes()).hexdigest()!=before:raise ValueError('Copy mismatch')
        payload[relative]=before;original_pins[original]=before
    for name in ['goal_observation_workflow.py','pressure_observations.py']:
        copy(Path(__file__).with_name(name),'code/'+name)
    for sid in ['S10','S11','B01-2']:
        for name in ['p','task.json','analysis_requests.json']:
            copy(replay/sid/'inputs'/name,'inputs/'+sid+'/'+name)
    for p,sha in original_pins.items():
        if hashlib.sha256(p.read_bytes()).hexdigest()!=sha:raise ValueError('Input changed during snapshot')
    (destination/'runner.py').write_text(RUNNER,encoding='utf-8')
    payload['runner.py']=hashlib.sha256((destination/'runner.py').read_bytes()).hexdigest()
    manifest={'scenes':['S10','S11','B01-2'],'payload_sha256':payload,'model_requests':0,'solver_calls':0,
              'third_party_dependencies':[],'os_sandbox_established':False,
              'python_binary_sha256':hashlib.sha256(Path(sys._base_executable).read_bytes()).hexdigest(),
              'remaining_external_dependency':'Python binary and standard library; -I -S disables environment/module-site injection, not OS file access'}
    (destination/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    pin=hashlib.sha256((destination/'manifest.json').read_bytes()).hexdigest()
    env={k:v for k,v in os.environ.items() if k.upper() in {'SYSTEMROOT','WINDIR','PATH','COMSPEC','PATHEXT'}}
    (destination/'tmp').mkdir();env.update(TMP=str(destination/'tmp'),TEMP=str(destination/'tmp'))
    process=subprocess.run([sys._base_executable,'-I','-S','-B',str(destination/'runner.py'),pin],cwd=destination,
                           env=env,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=60)
    (destination/'stdout.log').write_text(process.stdout,encoding='utf-8')
    (destination/'stderr.log').write_text(process.stderr,encoding='utf-8')
    print(json.dumps({'exit_code':process.returncode,'stdout':process.stdout,'stderr':process.stderr[:2000],'manifest_pin':pin}))
    if process.returncode:raise RuntimeError('Offline snapshot run failed; logs retained')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('replay',type=Path);parser.add_argument('destination',type=Path)
    args=parser.parse_args();prepare(args.replay,args.destination)
