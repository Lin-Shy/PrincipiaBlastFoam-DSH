"""Bounded persistent human-acceptance Web service; no experiment worker."""
from pathlib import Path
import fcntl,json,os,secrets,signal,subprocess,sys,threading,time
from dotenv import dotenv_values
APP=Path(__file__).resolve().parents[2]
WS=APP.parents[1]
ROOT=WS/'services/chapter3-web-20261123'
sys.path.insert(0,str(APP/'experiments/end2end'))
from model_budget import Gate,upstream
from model_budget_errors import serve
class PersistentGate(Gate):
 def __init__(self,root,model,forward):
  if not (root/'ledger.json').exists():
   super().__init__(root,model,100,4096,forward,{'temperature':0,'thinking':{'type':'disabled'}})
   self.save()
   return
  state=json.loads((root/'ledger.json').read_text())
  assert state['model']==model and state['max_requests']==100
  self.root=root;self.model=model;self.limit=100;self.output=4096;self.forward=forward
  self.generation={'temperature':0,'thinking':{'type':'disabled'}}
  self.lock=threading.Lock();self.token=secrets.token_urlsafe(32)
  self.events=state['events'];self.closed=state['closed']
  for event in self.events:
   if event['state']=='reserved':
    event['state']='unknown';event['error_type']='ServiceInterrupted';self.closed=True
  self.save()
def main():
 os.umask(0o077);ROOT.mkdir(parents=True,exist_ok=True)
 lock=(ROOT/'service.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 settings=dotenv_values(WS/'graduation-projects/.env.chapter3_dsh')
 assert settings['CHAPTER3_MODEL']=='deepseek-v4.1-flash'
 upstream_head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=WS/'deepseek-harness',text=True).strip()
 assert upstream_head=='d347e703908d0406b7a7ef80e3a0e594d86b2215'
 forward=upstream(settings['CHAPTER3_BASE_URL'],settings['CHAPTER3_API_KEY'],180)
 def bounded(body):
  if len(json.dumps(body).encode())>262144:raise ValueError('request input byte cap')
  try:return forward(body)
  except Exception as error:
   reason=getattr(error,"reason",error)
   (ROOT/"transport-diagnostic.json").write_text(json.dumps({"error_type":type(error).__name__,"reason_type":type(reason).__name__,"errno":getattr(reason,"errno",None),"certificate_error":isinstance(reason,__import__("ssl").SSLCertVerificationError)}))
   raise
 gate=PersistentGate(ROOT/'model',settings['CHAPTER3_MODEL'],bounded);server=serve(gate)
 work=ROOT/'workspace';work.mkdir(exist_ok=True);(work/'cases').mkdir(exist_ok=True)
 patch=[
 {'id':'session-title-llm','disabled':True},
 {'id':'skill-filesystem','config':{'includeDefaultRoots':False,'customSkillDirs':[]}},
 {'id':'llm-deepseek','disabled':True},
 {'id':'llm-pi-ai','config':{'providers':{'acceptance':{'api':'openai-completions','apiKeyEnv':'ACCEPTANCE_LOCAL_KEY','baseURL':'http://127.0.0.1:'+str(server.server_port)+'/v1','models':[{'id':settings['CHAPTER3_MODEL'],'contextWindow':131072,'maxTokens':4096,'input':['text']}],'compat':{'thinkingFormat':'deepseek'},'timeoutMs':210000,'retryPolicy':{'mode':'normal','maxRetries':0}}}}},
 {'id':'agent-default-model','config':{'provider':'acceptance','model':settings['CHAPTER3_MODEL']}},
 {'id':'sandbox-policy','config':{'mode':'danger-full-access','workspaceRoot':str(work)}},
 {'id':'approval','config':{'policy':'never'}},
 {'insert':[
 {'id':'principia-blastfoam-policy','name':(APP/'packages/principia-dsh-bundle/lib/index.js').as_uri()},
 {'id':'principia-domain-mcp','name':'@deepseek-ai/dsh-mcp-client','config':{
 'serverName':'principia_domain','transport':'stdio','command':str(WS/'.venv/bin/python'),
 'args':['-m','mcp_servers.principia_domain.server'],'cwd':str(APP),
 'env':{'PYTHONUTF8':'1','PYTHONPATH':str(APP/'src')+':'+str(APP),'PRINCIPIA_PROJECT_ROOT':str(APP),'PRINCIPIA_CASE_ROOT':str(work/'cases'),'ENABLE_EXECUTION':'false','REQUIRE_EXECUTION':'false','PRINCIPIA_LOCAL_MESH_ENABLED':'true','PRINCIPIA_LOCAL_MESH_BIN':str(WS/'runtime/mesh-bin'),'PRINCIPIA_TOOL_TRACE_DIR':str(ROOT/'tool-traces'),'PRINCIPIA_COMMAND_MCP_ENABLED':'true'},
 'toolCallTimeoutMs':60000,'failOnStartupError':True}}
 ]}]
 patch[-1]['insert'].append({
 'id':'simulation-cli-mcp','name':'@deepseek-ai/dsh-mcp-client','config':{
 'serverName':'simulation_cli','transport':'stdio','command':str(WS/'.venv/bin/python'),
 'args':['-m','mcp_servers.simulation_cli.server'],'cwd':str(APP),
 'env':{'PYTHONUTF8':'1','PYTHONPATH':str(APP/'src')+':'+str(APP),
 'PRINCIPIA_CASE_ROOT':str(work/'cases'),'SIMULATION_CLI_STATE':str(ROOT/'simulation-cli/tasks'),
 'SIMULATION_CLI_OPENFOAM':str(WS/'runtime/openfoam'),
 'SIMULATION_CLI_HPC_CONFIG':str(WS/'maintenance/simulation-cli-acceptance-20261123/hpc-config.json')},
 'toolCallTimeoutMs':60000,'failOnStartupError':True}})
 (ROOT/'web.patch.yml').write_text(json.dumps(patch,indent=2))
 env={k:v for k,v in os.environ.items() if not any(s in k.upper() for s in ('API_KEY','TOKEN','SECRET','PASSWORD'))}
 env.update(ACCEPTANCE_LOCAL_KEY=gate.token,DSH_HOME=str(ROOT/'dsh-home'),DSH_AGENTS_HOME=str(ROOT/'agents-home'),ENABLE_EXECUTION='false',REQUIRE_EXECUTION='false',PYTHONDONTWRITEBYTECODE='1')
 for name in ('dsh-home','agents-home'):(ROOT/name).mkdir(exist_ok=True)
 cmd=[str(WS/'bin/dsh-dev'),'--profile','web','--patch',str(ROOT/'web.patch.yml'),'--host','127.0.0.1','--port','3080','--no-open']
 child=None
 def stop(signum,frame):
  if child and child.poll() is None:child.terminate()
 signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
 with (ROOT/'web.stdout').open('w') as out,(ROOT/'web.stderr').open('w') as err:
  child=subprocess.Popen(cmd,cwd=work,env=env,stdout=out,stderr=err)
  (ROOT/'runtime.json').write_text(json.dumps({'supervisor_pid':os.getpid(),'web_pid':child.pid,'port':3080,'started_unix':time.time(),'upstream_commit':upstream_head}))
  try:return child.wait()
  finally:server.shutdown();gate.save()
if __name__=='__main__':sys.exit(main())
