"""完整会话的请求预算、实际模型身份及冻结零模型回放准入证据。"""
from __future__ import annotations
import argparse
from collections import Counter
from pathlib import Path
import leaderboard_audit as audit
import navigation_qa as qa


def complete_root_replay(root, expected, latest_result_mtime_ns):
    """Return the newest complete all-grid replay journal, if one exists.

    Some multi-arm runners wrap candidate implementations that do not emit a
    per-session invocation record.  Their root journal is still sufficient
    replay evidence when it is newer than every result, covers the exact
    frozen grid, and reports no errors.  Partial or stale journals never count.
    """
    candidates=[]
    for path in (root/'invocations').glob('*.json'):
        try:
            started=int(path.stem);record=audit.read(path)
        except (ValueError,TypeError):
            continue
        if (record.get('command')=='replay' and record.get('state')=='finished'
                and record.get('jobs')==expected and record.get('completed')==expected
                and record.get('errors')==[] and started>=latest_result_mtime_ns):
            candidates.append((started,path,record))
    return max(candidates,key=lambda row:row[0]) if candidates else None


def check(root):
    protocol=audit.verify(root);anchor=next(iter(protocol['groups']));questions=audit.read(root/anchor/'questions.json')
    maximum_model_calls=protocol.get('maximum_model_calls',9)
    maximum_generated_tokens=protocol.get('maximum_generated_tokens',8000)
    if (type(maximum_model_calls) is not int or maximum_model_calls<1
            or type(maximum_generated_tokens) is not int or maximum_generated_tokens<1):
        raise ValueError('invalid frozen model budget')
    models=Counter();fingerprints=Counter();errors=[];files={};count=0;replayed=0;terminal_failures=0
    expected=len(questions)*protocol['replicates']*sum(map(len,protocol['groups'].values()))
    result_paths=[]
    for group,methods in protocol['groups'].items():
        for method in methods:
            for q in questions:
                for rep in range(1,protocol['replicates']+1):
                    path=root/group/'sessions'/f"{q['id']}--{method}--r{rep}"/'result.json'
                    if path.exists():result_paths.append(path)
    latest_result_mtime_ns=max((p.stat().st_mtime_ns for p in result_paths),default=0)
    root_replay=complete_root_replay(root,expected,latest_result_mtime_ns)
    if root_replay:
        files[str(root_replay[1].relative_to(root))]=audit.sha(root_replay[1])
    for group,methods in protocol['groups'].items():
        for method in methods:
            for q in questions:
                for rep in range(1,protocol['replicates']+1):
                    folder=root/group/'sessions'/f"{q['id']}--{method}--r{rep}";result_path=folder/'result.json'
                    terminal=None
                    if not result_path.exists():
                        from leaderboard_results import terminal_failure
                        terminal=terminal_failure(folder)
                        if not terminal:errors.append({'session':str(folder.relative_to(root)),'error':'missing_answer'});continue
                        terminal_failures+=1
                    else:
                        count+=1;result=audit.read(result_path);files[str(result_path.relative_to(root))]=audit.sha(result_path)
                    requests=[]
                    for p in folder.glob('*.json'):
                        value=audit.read(p)
                        if 'request_sha256' not in value:continue
                        body=value['request'];requests.append(body);files[str(p.relative_to(root))]=audit.sha(p)
                        if qa.digest(qa.wire(body))!=value['request_sha256']:raise ValueError('request identity changed')
                        if body.get('model')!=protocol['model'] or body.get('temperature')!=0 or body.get('thinking')!={'type':'disabled'}:
                            errors.append({'session':str(folder.relative_to(root)),'error':'model_parameters_mismatch'})
                        if body.get('max_tokens')!=(2400 if p.name=='final.json' else 700):raise ValueError('per-request output budget changed')
                        if len(value['events'])>9:raise ValueError('transport attempt policy exceeded')
                        raw=value.get('raw_response',{})
                        if raw:
                            models[raw.get('model','missing')]+=1;fingerprints[raw.get('system_fingerprint') or 'missing']+=1
                    if (len(requests)>maximum_model_calls
                            or sum(b['max_tokens'] for b in requests)>maximum_generated_tokens):
                        raise ValueError('output budget exceeded')
                    if terminal:continue
                    if result['returned_characters']>24000 or any(e.get('returned_characters',0)>6000 for e in result['events']):
                        raise ValueError('returned evidence budget exceeded')
                    verified=[]
                    for p in (folder/'invocations').glob('*.json'):
                        record=audit.read(p)
                        if record.get('replay') and record.get('status') in {'complete','incomplete_answer'} and record.get('started_unix_ns',0)>=result_path.stat().st_mtime_ns:
                            verified.append(p)
                    if verified:
                        replayed+=1;p=max(verified,key=lambda p:p.name);files[str(p.relative_to(root))]=audit.sha(p)
                    elif root_replay:
                        replayed+=1
                    else:errors.append({'session':str(folder.relative_to(root)),'error':'successful_replay_missing_after_result'})
    identity=set(models)=={protocol['model']} and len(fingerprints)==1 and 'missing' not in fingerprints
    return {'schema':'leaderboard-admission-v1','passed':count+terminal_failures==expected and replayed==count and identity and not errors,
            'protocol_sha256':audit.sha(root/'protocol.json'),'expected':expected,'answers':count,'terminal_failures':terminal_failures,'replayed':replayed,
            'complete_root_replay':str(root_replay[1].relative_to(root)) if root_replay else None,
            'provider_models':dict(models),'provider_fingerprints':dict(fingerprints),'errors':errors,'files':files,
            'maximum_model_calls':maximum_model_calls,
            'maximum_generated_tokens':maximum_generated_tokens,
            'scope':'frozen source and corpus identities; every saved request, public budget and successful per-session replay after result creation; source quality review is a separate gate'}


if __name__=='__main__':
    cli=argparse.ArgumentParser(description=__doc__);cli.add_argument('--run',type=Path,required=True);cli.add_argument('--output',type=Path,required=True)
    a=cli.parse_args();result=check(a.run.resolve());audit.save(a.output,result)
    print(qa.wire({k:v for k,v in result.items() if k not in {'files','errors','scope'}}))
