"""One explicitly authorized reattempt of failed generation tasks.

Valid generated answers, including wrong or unparseable answers, are reused.
Original failure and unknown-receipt records remain in the parent archive.
"""
import argparse
import os
from pathlib import Path
import shutil
import sys
from types import ModuleType
import objective_experiment as base
import objective_json_pilot as pilot
import objective_json_strict as strict
import objective_json_transition as previous
from objective_json_resume_guarded import CircuitBreaker, health

PARENT = previous.OUT
OUT = base.BASE/'objective_json_v5_failure_rerun'
DATA = base.DATA


def rerun_needed(result):
    return result.get('status') != 'answered'


def prepare():
    if (OUT/'manifest.json').exists():
        raise ValueError('Rerun batch already frozen')
    previous.use_transition(); m=base.verify(); qs=base.read(base.DATA/'model/questions.json')
    source_manifest=base.sha(PARENT/'manifest.json'); reused=[]; rerun=[]
    for c in m['configurations']:
        for q in qs:
            path=PARENT/'generation'/c['config_id']/q['id']/'result.json'
            r=base.read(path); item=dict(config_id=c['config_id'],id=q['id'],
                source_sha256=base.sha(path),source_manifest_sha256=r['manifest_sha256'],source_status=r['status'])
            if not rerun_needed(r):
                target=OUT/'generation'/c['config_id']/q['id']/'result.json';target.parent.mkdir(parents=True,exist_ok=True)
                try:os.link(path,target)
                except OSError:shutil.copy2(path,target)
                reused.append(item)
            else:
                rerun.append(item)
    if len(reused)+len(rerun)!=m['tasks'] or not rerun:raise ValueError('Unexpected parent task inventory')
    base.save(OUT/'reuse_inventory.json',reused);base.save(OUT/'rerun_inventory.json',rerun)
    bindings=dict(m['bindings'])
    for p in (Path(__file__),PARENT/'manifest.json',OUT/'reuse_inventory.json',OUT/'rerun_inventory.json'):
        bindings[str(p.relative_to(base.WORK)).replace('\\','/')]=base.sha(p)
    m.update(schema='objective_json_failure_rerun_v1',created=base.now(),bindings=bindings,
             parent_manifest_sha256=source_manifest,reused_tasks=len(reused),rerun_tasks=len(rerun),
             rerun_authorization='User explicitly requested rerun of original failed tasks after completion.',
             rerun_policy='One new attempt per failed task, including previously unknown receipts; all source records retained. Answered tasks never rerun, regardless of correctness or parseability. No automatic HTTP retries in this batch.',
             uncertainty='Some original failed requests may have reached the prior service; user explicitly requested rerun after receipt review. This is a post-hoc recovery and not a preregistered independent test.')
    base.save(OUT/'manifest.json',m)
    print('Failure rerun prepared:',len(reused),'answered reused;',len(rerun),'failed scheduled')


def use():
    base.OUT=OUT;base.MANIFEST=OUT/'manifest.json';base.DATA=DATA
    base.SUPERCOMPUTER_SETTINGS=previous.PRIVATE;base.FORMAT=pilot.FORMAT;base.question_text=pilot.question_text


def run():
    use();health()
    import dev40_supplement as transport
    original8=base.supercomputer_client;original14=transport.client
    circuits={'8':CircuitBreaker(),'14':CircuitBreaker()}
    def guard(client,key):
        def call(body,turn):
            response=client(body,turn);circuits[key].observe(response)
            if response.get('http_status') in (429,500,502,503,504):
                response=dict(response,original_http_status=response['http_status'],http_status=None)
            return response
        return call
    base.supercomputer_client=lambda folder:guard(original8(folder),'8')
    transport.client=lambda folder,model:guard(original14(folder,model),'14')
    base.run()


def report():
    use();adapter=ModuleType('objective_scoring');adapter.score=strict.score;sys.modules['objective_scoring']=adapter
    base.report()
    page=OUT/'results/index.html';html=page.read_text(encoding='utf8')
    html=html.replace('<h1>第2章客观题实验</h1>','<h1>第2章客观题实验</h1><p><strong>本批对原生成失败任务进行一次事后补试；原始失败与未知回执保留。已有回答没有重跑。补试结果不能视为预注册或未见测试。</strong></p>')
    page.write_text(html,encoding='utf8')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('command',choices=('prepare','run','report'));a=p.parse_args()
    if a.command=='prepare':prepare()
    elif a.command=='run':run()
    else:report()
