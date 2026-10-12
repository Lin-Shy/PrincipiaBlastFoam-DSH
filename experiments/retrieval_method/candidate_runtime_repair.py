"""零API验证并迁移运行时修复前的同请求轨迹；不按答案质量挑选会话。"""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
import fcntl
from pathlib import Path
import shutil
import sys


def main():
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--old',type=Path,required=True);cli.add_argument('--new',type=Path,required=True);a=cli.parse_args()
    old=a.old.resolve();new=a.new.resolve();sys.path.insert(0,str(new))
    import candidate_qa as candidate
    import navigation_qa as qa
    import leaderboard_audit as audit
    from contextlib import ExitStack
    with ExitStack() as stack:
        for root in [old,new]:
            lock=stack.enter_context((root/'runtime.lock').open('a+'));fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        parent=audit.verify(old);protocol=audit.verify(new)
        for key in ['groups','model','corpus_id','replicates','options','parent_protocol_sha256','max_generated_tokens','max_model_calls']:
            if parent[key]!=protocol[key]:raise ValueError('engineering repair changed experiment: '+key)
        qa.instrument_file_reads()
        original_fetch=candidate.base.fetch
        def audited_fetch(folder,name,body,key):
            path=folder/(name+'.json')
            if path.exists() and qa.read(path)['request_sha256']!=qa.digest(qa.wire(body)):
                saved=qa.read(path)['request'];differences=[]
                for index,(left,right) in enumerate(zip(saved['messages'],body['messages'])):
                    if left!=right:
                        x=left['content'];y=right['content'];at=next((j for j,(a,b) in enumerate(zip(x,y)) if a!=b),min(len(x),len(y)))
                        differences.append({'message':index,'offset':at,'old_excerpt':x[max(0,at-50):at+100],'new_excerpt':y[max(0,at-50):at+100]})
                raise ValueError('request drift '+str(path)+' '+qa.wire(differences))
            return original_fetch(folder,name,body,key)
        candidate.base.fetch=audited_fetch
        engines={g:candidate.Engine(old/g,g,new/'hybrid',new/'candidate-graph.json' if g=='full_candidate' else None,protocol['options']) for g in protocol['groups']}
        def probe(group):
            s=candidate.Session(engines[group],'retrieval_first','movingCone dynamicMeshDict mesh motion')
            result,_=s.dispatch({'action':'locate','needs':['mesh configuration']},6000)
            if result['status']!='ok' or not s.seen:raise ValueError('concurrent model initialization failed')
            return {'group':group,'status':'passed','graph_loaded':engines[group].backend.graph is not None}
        with ThreadPoolExecutor(max_workers=2) as pool:probes=list(pool.map(probe,engines))
        records=[];origin={};questions={q['id']:q for q in qa.read(old/'control/questions.json')}
        for group,e in engines.items():
            for folder in sorted((old/group/'sessions').glob('*')):
                if not folder.is_dir():continue
                qid,method,rep=folder.name.split('--');q=questions[qid];session=candidate.Session(e,method,q['question'])
                for path in sorted((folder/'tool_events').glob('*.json')):
                    event=qa.read(path);cap=min(6000,24000-800-sum(x['returned_characters'] for x in records if x.get('session')==folder.name and x.get('group')==group))
                    result,_=session.dispatch(event['action'],cap)
                    if qa.wire(result)!=qa.wire(event['result']):raise ValueError('saved retrieval prefix differs after runtime repair: '+str(path))
                    records.append({'group':group,'session':folder.name,'tool_event':path.name,'returned_characters':event['returned_characters']})
                if (folder/'result.json').exists():
                    print('REPLAY',group,folder.name,flush=True)
                    candidate.run_one(e,q,method,None,int(rep[1:]),replay=True)
                for path in folder.rglob('*'):
                    if path.is_file():origin[str(path.relative_to(old))]=audit.sha(path)
        # Every recorded session is transferred, including failed/in-flight requests, after prefix validation.
        for group in engines:
            source=old/group/'sessions';target=new/group/'sessions'
            if target.exists():raise FileExistsError('never overwrite target sessions')
            if source.exists():shutil.copytree(source,target)
        certificate={'status':'passed','api_calls':0,'parent_run':str(old),'parent_protocol_sha256':audit.sha(old/'protocol.json'),
            'concurrent_probes':probes,'verified_tool_prefixes':len(records),'completed_answers_replayed':len(list(old.glob('*/sessions/*/result.json'))),
            'origin_files':origin,'selection':'all recorded sessions; no answer-quality selection or regeneration',
            'repair':'shared lock around pinned embedding model construction and encoding; reject unmaterialized parameters; prompts, corpus, graph, evidence budget and model requests unchanged'}
        audit.save(new/'engineering-resume.json',certificate)
        shutil.copy2(Path(__file__),new/'candidate_runtime_repair.py')
        protocol['files']['engineering-resume.json']=audit.sha(new/'engineering-resume.json')
        protocol['files']['candidate_runtime_repair.py']=audit.sha(new/'candidate_runtime_repair.py')
        protocol['engineering_parent_run']=str(old);protocol['engineering_parent_protocol_sha256']=audit.sha(old/'protocol.json')
        audit.save(new/'protocol.json',protocol);audit.verify(new)
        print(qa.wire({k:v for k,v in certificate.items() if k not in {'origin_files','repair','selection'}}))


if __name__=='__main__':main()
