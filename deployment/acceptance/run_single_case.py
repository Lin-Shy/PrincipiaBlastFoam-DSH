"""Run one explicitly authorized live-model acceptance through the normal DSH profile."""
from pathlib import Path
import hashlib,json,os,signal,subprocess,sys,time
from dotenv import dotenv_values
HERE=Path(__file__).resolve().parent
APP=HERE.parents[1]
WS=APP.parents[1]
sys.path.insert(0,str(APP/'experiments/end2end'))
from model_budget import Gate,upstream
from model_budget_errors import serve

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 run=Path(sys.argv[1]).resolve() if len(sys.argv)>1 else WS/'runs/real-model-single-case-20261123'
 protocol=json.loads((run/'protocol.json').read_text())
 workspace=Path(protocol.get('task_workspace',str(run/'workspace')))
 assert 1<=protocol['model_requests_max']<=40 and protocol['simulation_jobs_max']==1
 with (run/'launch_intent.json').open('x') as f:json.dump({'time':time.time(),'protocol_sha256':sha(run/'protocol.json')},f)
 settings=dotenv_values(WS/'graduation-projects/.env.chapter3_dsh')
 assert all(settings.get(x) for x in ('CHAPTER3_API_KEY','CHAPTER3_BASE_URL','CHAPTER3_MODEL'))
 assert settings['CHAPTER3_MODEL']==protocol['model']
 forward=upstream(settings['CHAPTER3_BASE_URL'],settings['CHAPTER3_API_KEY'],180)
 def bounded(body):
  if len(json.dumps(body).encode())>262144:raise ValueError('request exceeds input byte cap')
  if time.monotonic()-started>1200:raise TimeoutError('acceptance wall time exceeded')
  try:return forward(body)
  except Exception as exc:
   reason=getattr(exc,'reason',exc)
   detail={'type':type(exc).__name__,'reason_type':type(reason).__name__,'errno':getattr(reason,'errno',None)}
   # No URL, credential or arbitrary exception body is logged.
   (run/'transport-failure.json').write_text(json.dumps(detail,indent=2))
   raise
 started=time.monotonic()
 gate=Gate(run/'model',protocol['model'],protocol['model_requests_max'],4096,bounded,{'temperature':0,'thinking':{'type':'disabled'}})
 server=serve(gate)
 patch=[
 {'id':'session-title-llm','disabled':True},
 {'id':'skill-filesystem','config':{'includeDefaultRoots':False,'customSkillDirs':[]}},
 {'id':'llm-deepseek','disabled':True},
 {'id':'llm-pi-ai','config':{'providers':{'acceptance':{'api':'openai-completions','apiKeyEnv':'ACCEPTANCE_LOCAL_KEY','baseURL':'http://127.0.0.1:'+str(server.server_port)+'/v1','models':[{'id':protocol['model'],'contextWindow':131072,'maxTokens':4096,'input':['text']}],'compat':{'thinkingFormat':'deepseek'},'timeoutMs':210000,'retryPolicy':{'mode':'normal','maxRetries':0}}}}},
 {'id':'agent-default-model','config':{'provider':'acceptance','model':protocol['model']}},
 {'id':'sandbox-policy','config':{'mode':'danger-full-access','workspaceRoot':str(workspace)}},
 {'id':'approval','config':{'policy':'never'}},
 {'insert':[{'id':'principia-blastfoam-policy','name':(APP/'packages/principia-dsh-bundle/lib/index.js').as_uri()}]}
 ]
 (run/'live.patch.yml').write_text(json.dumps(patch,indent=2))
 env={k:v for k,v in os.environ.items() if not any(s in k.upper() for s in ('API_KEY','TOKEN','SECRET','PASSWORD'))}
 env.update(ACCEPTANCE_LOCAL_KEY=gate.token,DSH_HOME=str(run/'dsh-home'),DSH_AGENTS_HOME=str(run/'agents-home'),
 DSH_TELEMETRY_MODE='DISABLED',ENABLE_EXECUTION='false',REQUIRE_EXECUTION='false',PYTHONDONTWRITEBYTECODE='1')
 for d in ['dsh-home','agents-home']:(run/d).mkdir(exist_ok=True)
 cmd=[str(WS/'bin/dsh-dev'),'--profile','headless','--patch',str(run/'live.patch.yml'),Path(protocol.get('task_prompt_file',str(workspace/'TASK.md'))).read_text()]
 report={'normal_entry':'dsh-dev --profile headless','research_experiment':False,'operator_simulation_jobs':0}
 try:
  with (run/'evidence/profile-config.yml').open('w') as out,(run/'evidence/profile-config.stderr').open('w') as err:
   check=subprocess.run(cmd[:-1]+['--dump-config'],cwd=workspace,env=env,stdout=out,stderr=err,timeout=60)
  if check.returncode:raise RuntimeError('Normal profile config preflight failed')
  with (run/'agent.stdout').open('w') as out,(run/'agent.stderr').open('w') as err:
   child=subprocess.Popen(cmd,cwd=workspace,env=env,stdout=out,stderr=err,start_new_session=True)
   (run/'agent.pid').write_text(str(child.pid))
   deadline=time.monotonic()+1200
   while child.poll() is None:
    if time.monotonic()>deadline or sum(p.stat().st_size for p in run.rglob('*') if p.is_file())>200*1024*1024:
     os.killpg(child.pid,signal.SIGTERM);report['stopped_by_operator_guard']=True;break
    time.sleep(2)
   try:report['exit_code']=child.wait(timeout=10)
   except subprocess.TimeoutExpired:
    os.killpg(child.pid,signal.SIGKILL);report['exit_code']=child.wait()
 finally:
  server.shutdown();gate.save()
  report.update(elapsed_seconds=time.monotonic()-started,model_requests=len(gate.events),
    settled=sum(x['state']=='settled' for x in gate.events),unknown=sum(x['state']=='unknown' for x in gate.events))
  (run/'run-summary.json').write_text(json.dumps(report,indent=2))
  print(json.dumps(report),flush=True)
if __name__=='__main__':main()
