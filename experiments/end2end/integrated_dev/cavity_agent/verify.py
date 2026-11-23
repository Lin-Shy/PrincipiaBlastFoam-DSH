"""Read-only check of a model's sealed OpenFOAM cavity modification delivery."""
import json,math,re,zipfile,tarfile,hashlib
from run import PAIR,ROOT,FILES,read,sha,write
def parse(raw,vector):
 s=raw.decode("utf-8-sig")
 match=re.search(r'internalField\s+nonuniform\s+List<\w+>\s+(\d+)\s*\((.*?)\n\)\s*;',s,re.S)
 assert match
 values=[float(x) for x in re.findall(r'[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?',match[2])]
 n=int(match[1]);assert len(values)==n*(3 if vector else 1) and all(math.isfinite(x) for x in values)
 return n,values
def main():
 seal=read(ROOT/"sealed.json")
 assert sha(ROOT/"submission.zip")==seal["archive_sha256"]
 term=read(PAIR/"terminal.json")
 assert term["JobState"]=="COMPLETED" and term["ExitCode"]=="0:0"
 rec=read(ROOT/"workspace/exchange/receipt.json")
 assert sha(PAIR/"operator/collected.tar")==rec["archive_sha256"]
 with tarfile.open(PAIR/"operator/collected.tar") as tar:
  native=lambda n:tar.extractfile("./"+n).read()
  assert native("logs/allocated_job_id.txt").strip().decode()==rec["job_id"]
  assert native("logs/pipeline.exit").strip()==b"0"
  log=native("logs/icoFoam.log").decode()
  times=re.findall(r'^Time = ([\d.]+)$',log,re.M)
  assert len(times)==20 and float(times[-1])==.1 and log.rstrip().endswith("End")
  assert b"Mesh OK." in native("logs/checkMesh.log")
  n,u=parse(native("case/0.1/U"),True);np,p=parse(native("case/0.1/p"),False)
  assert n==np==100
  expected=dict(cells=n,final_time=.1,max_speed_m_s=max(math.sqrt(sum(x*x for x in u[i:i+3])) for i in range(0,len(u),3)),mean_pressure_m2_s2=math.fsum(p)/n)
  with zipfile.ZipFile(ROOT/"submission.zip") as z:
   required=[*[f"case/{n}" for n in FILES],"receipt.json","postprocess.py","summary.json","README.md"]
   missing=[n for n in required if n not in z.namelist()]
   assert not missing,missing
   assert json.loads(z.read("receipt.json"))==rec
   for f in FILES:assert z.read("case/"+f).replace(b"\r\n",b"\n")==(PAIR/"payload/case"/f).read_bytes().replace(b"\r\n",b"\n")
   for f,h in rec["files"].items():assert hashlib.sha256(z.read("native/"+f)).hexdigest()==h
   summary=json.loads(z.read("summary.json").decode("utf-8-sig"))
   agreement={k:type(summary.get(k)) in (int,float) and abs(summary[k]-v)<=1e-8 for k,v in expected.items()}
   bmesh=z.read("case/system/blockMeshDict").decode()
   boundary=z.read("case/0/U").decode()
   control=z.read("case/system/controlDict").decode()
   strip=lambda s:re.sub(r'/\*.*?\*/|//[^\n]*','',s,flags=re.S)
   settings=dict(mesh=bool(re.search(r'\(\s*10\s+10\s+1\s*\)',strip(bmesh))),
      lid=bool(re.search(r'movingWall\s*\{[^}]*value\s+uniform\s*\(\s*0\.5\s+0\s+0\s*\)',strip(boundary))),
      dt=bool(re.search(r'deltaT\s+0\.005\s*;',strip(control))),
      end=bool(re.search(r'endTime\s+0\.1\s*;',strip(control))))
 write(ROOT/"independent.json",dict(job=rec["job_id"],expected_summary=expected,summary_fields=agreement,settings=settings,all_passed=all(agreement.values()) and all(settings.values()),reproduction="pending clean README replay"))
 print(expected,agreement,settings)
if __name__=="__main__":main()

