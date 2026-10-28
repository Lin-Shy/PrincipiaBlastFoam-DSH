"""Durable operational supervision; no scores are read for scheduling."""
import argparse
from collections import Counter
import json
import os
import re
from pathlib import Path
import socket
import subprocess
import sys
import time

import single_pass_dev40 as s
import test160_evaluation as evaluation
from central_execution import exclusive_lock

BASE = s.RUN / 'test160_runs'
HERE = Path(__file__).resolve().parent


def running_lock(path):
    if not path.exists():
        return False
    # Locks belonging to an exited process are not silently removed.
    return True


def start(script, args, name):
    stdout = (BASE / (name + '.stdout.log')).open('a', encoding='utf-8')
    stderr = (BASE / (name + '.stderr.log')).open('a', encoding='utf-8')
    flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    p = subprocess.Popen([sys.executable, '-u', str(HERE/script)] + args,
                         cwd=str(s.WORKSPACE), stdout=stdout, stderr=stderr,
                         creationflags=flags)
    stdout.close(); stderr.close()
    s.append(BASE/'controller_events.jsonl', dict(utc=s.now(), kind='start', name=name, pid=p.pid))
    return p


def main(authorization):
    manifest, questions = evaluation.authorize(authorization, 'single_pass')
    children = {}
    attempts = Counter()
    with exclusive_lock(BASE/'controller.lock'):
        while True:
            status = {}
            for mode, prefix in [('agentic', BASE), ('single_pass', BASE/'supplement/single_pass')]:
                for model in ['qwen3_8b', 'qwen3_14b']:
                    configs = [c for c in manifest['configurations'] if c['model_key']==model and (mode=='agentic' or c['method_id'] in ('graph','bm25','bge_m3'))]
                    counts = Counter()
                    for c in configs:
                        for q in questions:
                            folder = prefix/'generation'/c['config_id']/q['id']
                            if (folder/'result.json').exists():
                                try: counts[s.load(folder/'result.json')['status']] += 1
                                except (OSError, json.JSONDecodeError): counts['writing'] += 1
                            elif list((folder/'requests').glob('*.request.json')):
                                counts['in_flight_or_unresolved'] += 1
                            elif (folder/'branch_hold.json').exists():
                                counts['service_held_unsent'] += 1
                            else:
                                counts['not_sent'] += 1
                    terminal = sum(v for k,v in counts.items() if k not in ('writing','in_flight_or_unresolved','service_held_unsent','not_sent'))
                    status[mode+'|'+model] = dict(expected=len(configs)*160, terminal=terminal, states=dict(counts))
            # The initial frozen executor owns both lanes until all 2080 log entries
            # for a model have been emitted. Never race its pending tasks.
            lane_finished = set()
            log = BASE/'agentic.stdout.log'
            if log.exists():
                # The frozen executor's two print lanes can concatenate JSON
                # records on one line. Count complete model fields, not lines.
                emitted = Counter(re.findall(r'"model": "([^"]+)"', log.read_text(encoding='utf-8')))
                lane_finished = {k for k,v in emitted.items() if v==2080}
            for model in ['qwen3_8b','qwen3_14b']:
                name = 'resume_'+model
                current = children.get(name)
                if (model in lane_finished and status['agentic|'+model]['terminal']<2080
                    and (current is None or current.poll() is not None)
                    and not running_lock(BASE/('generation_'+model+'.lock'))
                    and attempts[name]<3):
                    route = manifest['deployments'][model]
                    from urllib.parse import urlsplit
                    address = urlsplit(route['endpoint'])
                    try:
                        conn = socket.create_connection((address.hostname,address.port or (443 if address.scheme=='https' else 80)),timeout=120 if model=='qwen3_8b' else 15)
                        conn.close()
                    except OSError:
                        continue
                    # Release only explicit empty scheduler reservations, never a
                    # request/response or a terminal generation failure.
                    released = 0
                    for marker in (BASE/'generation').glob(model+'*/*/branch_hold.json'):
                        folder=marker.parent; requests=folder/'requests'
                        if (folder/'result.json').exists() or not requests.exists() or any(requests.iterdir()):
                            continue
                        requests.rmdir(); marker.unlink(); released+=1
                    s.append(BASE/'controller_events.jsonl', dict(utc=s.now(),kind='release_unsent_service_holds',model=model,count=released))
                    children[name] = start('test160_live.py', ['agentic','--authorization',str(authorization),'--model',model], name)
                    attempts[name] += 1
                spname='single_pass_'+model
                if status['agentic|'+model]['terminal']==2080 and status['single_pass|'+model]['terminal']<480:
                    if spname not in children and not running_lock(BASE/'supplement/single_pass'/('generation_'+model+'.lock')):
                        children[spname]=start('test160_live.py', ['single_pass','--authorization',str(authorization),'--model',model], spname)
            status.update(updated_utc=s.now(), pid=os.getpid(), children={k:dict(pid=p.pid,exit_code=p.poll()) for k,p in children.items()},
                          manifest_sha256=s.sha(evaluation.runner.MANIFEST), scores_used_for_scheduling=False)
            s.save(BASE/'controller_status.json',status)
            import test160_progress
            test160_progress.render(status)
            # Only the complete formal matrix may trigger final score analysis.
            generated=all(status[mode+'|'+model]['terminal']==n for mode,n in [('agentic',2080),('single_pass',480)] for model in ['qwen3_8b','qwen3_14b'])
            scored=True
            for prefix,n in [(BASE,4160),(BASE/'supplement/single_pass',960)]:
                fp=prefix/'scoring/stream_status.json'
                v=s.load(fp) if fp.exists() else {}
                scored &= v.get('bound_answers')==n and v.get('completed_evaluations')==n*2 and not v.get('active_or_queued')
            if generated and scored:
                p=start('test160_report.py',['--authorization',str(authorization)],'final_report')
                code=p.wait()
                s.save(BASE/'completion.json',dict(utc=s.now(),generation_complete=True,scoring_reconciled=True,report_exit_code=code,completed=code==0))
                return
            time.sleep(30)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--authorization',type=Path,required=True)
    main(p.parse_args().authorization)
