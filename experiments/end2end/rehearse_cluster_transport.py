"""Real loopback client/service/bridge, mocked SSH/scheduler/transfer only."""
import argparse
import io
import json
import os
from pathlib import Path
import tarfile
import types
import cluster_job
from cluster_service import Service,serve
from cluster_client import call

def rehearse(root):
    root.mkdir(parents=True,exist_ok=False);workspace=root/'workspace';payload=workspace/'payload';payload.mkdir(parents=True)
    (payload/'run_case.sh').write_text('# mock input only; never executed\n')
    state=root/'operator_state';run_id='c3-offline-transport';commands=[]
    config={'partition':'fixture','tasks':1,'wall_minutes':1,'memory_mib':128,'openfoam_bashrc':'/fixture/of','blastfoam_bashrc':'/fixture/blast','ssh_config':'FAKE','ssh_target':'FAKE','hpc_entry':'FAKE'}
    grant={'live_actions_allowed':True,'run_ids':[run_id],'actions':['stage','submit','status','collect'],'limits':{'tasks':1,'wall_minutes':1,'memory_mib':128}}
    archive=io.BytesIO()
    with tarfile.open(fileobj=archive,mode='w') as tar:
        data=b'FAKE TRANSPORT ONLY; NO SOLVER EXECUTED\n';info=tarfile.TarInfo('README.txt');info.size=len(data);tar.addfile(info,io.BytesIO(data))
    def fake_ssh(config,command,**kwargs):
        commands.append(command)
        if 'sha256sum' in command:return types.SimpleNamespace(stdout=cluster_job.digest(state/'payload.tar')+' payload.tar')
        if command.startswith('yhbatch'):return types.SimpleNamespace(stdout='Submitted batch job 12345\n')
        if command.startswith('scontrol'):return types.SimpleNamespace(stdout='MOCK JobId=12345 JobState=COMPLETED')
        if command.startswith('tar -C'):kwargs['stdout'].write(archive.getvalue())
        return types.SimpleNamespace(stdout='')
    cluster_job.ssh=fake_ssh
    cluster_job.subprocess.run=lambda args,**kwargs:commands.append(args)
    service=Service(workspace,state,config,grant,run_id);server=serve(service)
    os.environ['C3_CLUSTER_ENDPOINT']=f'http://127.0.0.1:{server.server_port}';os.environ['C3_CLUSTER_TOKEN']=service.token
    try:
        replies={action:call(action) for action in ['plan','stage','submit','status','collect']}
        before=len(commands);again=call('collect');assert len(commands)==before
        assert (workspace/'returned/collected.tar').read_bytes()==archive.getvalue()
        assert replies['status']['scientific_success']=='not_assessed'
        result={'client_service_bridge':'passed','cached_recollection_without_remote_call':True,'mock_transport_operations':len(commands),
            'real_remote_calls':0,'real_jobs':0,'solver_calls':0,'simulation_success':False,'port':server.server_port}
        (root/'result.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result))
    finally:server.shutdown();server.server_close()

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('destination',type=Path);a=p.parse_args();rehearse(a.destination.resolve())
