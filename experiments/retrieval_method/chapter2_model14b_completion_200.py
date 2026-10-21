"""Close the authorized 14B run, then judge and analyze without overlapping calls."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
from chapter2_optimization_200 import PROJECT, read, save, sha
from chapter2_publication_200 import verify


def main(root):
    protocol=verify(root)
    authorization=read(root/'user-authorization.json')
    if (protocol['answer_model']!='qwen3-14b' or protocol['generation_sessions']!=1400
            or not authorization.get('explicit_data_export_approved')
            or not authorization.get('generation_and_scoring_export')
            or sha(root/'user-authorization.json')!=protocol['authorization_sha256']):
        raise ValueError('Exact authorized 14B experiment required')
    source=Path(__file__)
    analysis=source.with_name('chapter2_model14b_analysis_200.py')
    save(root/'completion-pipeline-protocol.json',dict(
        formal_protocol_sha256=sha(root/'protocol.json'),
        pipeline_source_sha256=sha(source),analysis_source_sha256=sha(analysis),
        sequence=['wait_generation','audit_original_sources_and_requests','prepare_frozen_judge_material',
                  'score_one_attempt_zero_reviews','reparse_and_analyze'],
        judge_model='qwen3-14b',judge_concurrency=16,
        overlap='No scoring requests until all generation processes have exited',
        no_new_answer_calls=True,no_retries=True))
    def run(name,*args):
        log=root/'logs'/(name+'.log')
        with log.open('x',encoding='utf-8') as output:
            subprocess.run([sys.executable,'-X','utf8',str(source.with_name(name+'.py')),*map(str,args)],
                cwd=PROJECT,stdout=output,stderr=subprocess.STDOUT,check=True)
        print('completed',name,flush=True)
    while not (root/'generation-controller-completion.json').exists():
        time.sleep(5)
    if not read(root/'generation-controller-completion.json')['complete']:
        raise ValueError('Generation controller failed; no automatic replay')
    run('chapter2_model14b_generation_audit','--root',root,'--final')
    audit=read(root/'generation-audit.json')
    if audit['answered']==0:
        raise ValueError('No delivered answer; do not treat a fully inaccessible API as model performance')
    scoring=root/'scoring_001'
    run('chapter2_formal_scoring_200','prepare','--root',root,'--output',scoring)
    # Separate logs for prepare/run, without changing the frozen scoring driver.
    log=root/'logs/scoring-run.log'
    with log.open('x',encoding='utf-8') as output:
        subprocess.run([sys.executable,'-X','utf8',str(source.with_name('chapter2_formal_scoring_200.py')),
            'run','--root',str(root),'--output',str(scoring)],cwd=PROJECT,
            stdout=output,stderr=subprocess.STDOUT,check=True)
    print('completed scoring',flush=True)
    if sha(analysis)!=read(root/'completion-pipeline-protocol.json')['analysis_source_sha256']:
        raise ValueError('Planned analysis source drift')
    run('chapter2_model14b_analysis_200','--root',root,'--scoring',scoring,'--output',root/'analysis_001')
    save(root/'completion-pipeline-complete.json',dict(
        formal_protocol_sha256=sha(root/'protocol.json'),generation_audit_sha256=sha(root/'generation-audit.json'),
        scoring_completion_sha256=sha(scoring/'completion.json'),
        analysis_summary_sha256=sha(root/'analysis_001/summary.json'),completed=True))
    print('14B generation, audit, scoring and statistics complete',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    main(parser.parse_args().root.resolve())
