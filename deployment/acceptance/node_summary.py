"""Runs only in the allocated batch, summarizing bounded ordinary-fluid fields."""
from pathlib import Path
import hashlib,json,math,os,re,subprocess
root=Path.cwd()
case=root/'case'
assert os.environ.get('SLURM_JOB_ID')
u=(case/'0.02/U').read_text()
p=(case/'0.02/p').read_text()
def values(text,vector):
 match=re.search(r'internalField\s+nonuniform\s+List<[^>]+>\s+(\d+)\s*\((.*?)\)\s*;',text,re.S)
 if not match: raise ValueError('Expected nonuniform field')
 n=int(match[1])
 if vector:
  rows=[tuple(map(float,x.split())) for x in re.findall(r'\(([^()]+)\)',match[2])]
 else: rows=[float(x) for x in match[2].split()]
 assert len(rows)==n and n==100
 return rows
uv=values(u,True); pv=values(p,False)
assert all(math.isfinite(v) for row in uv for v in row)
assert all(math.isfinite(v) for v in pv)
mesh=(root/'logs/checkMesh.log').read_text()
solver=(root/'logs/icoFoam.log').read_text()
assert 'Mesh OK.' in mesh and 'End' in solver
files={}
total=0
for f in sorted(case.rglob('*')):
 if f.is_file():
  n=f.stat().st_size;total+=n
  files[str(f.relative_to(root))]={'bytes':n,'sha256':hashlib.sha256(f.read_bytes()).hexdigest()}
assert total<=100*1024*1024
summary={'schema':'single-case-node-summary-v1','job_id':os.environ['SLURM_JOB_ID'],
 'hostname':subprocess.check_output(['hostname','-s'],text=True).strip(),
 'target_time':0.02,'cells':100,'mesh_ok':True,'finite_fields':True,
 'max_internal_speed':max(math.sqrt(sum(v*v for v in row)) for row in uv),
 'pressure_min':min(pv),'pressure_max':max(pv),'native_bytes':total,
 'native_results':str(case),'files':files}
(root/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
