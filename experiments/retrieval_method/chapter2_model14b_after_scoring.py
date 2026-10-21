"""Run only the preplanned local analysis after the existing scorer closes."""
from pathlib import Path
import subprocess
import sys
import time
from chapter2_optimization_200 import PROJECT, read, save, sha

R=PROJECT.parent/'graduation-experiment-results/chapter2_retrieval/current/model14b_200_20261019_002'


def main():
    source=Path(__file__)
    planned=read(R/'completion-pipeline-protocol.json')
    analysis=source.with_name('chapter2_model14b_analysis_200.py')
    assert sha(analysis)==planned['analysis_source_sha256']
    while not (R/'scoring_001/completion.json').exists():
        time.sleep(5)
    completion=read(R/'scoring_001/completion.json')
    assert completion['sessions']==1400
    with (R/'logs/analysis.log').open('x',encoding='utf-8') as output:
        subprocess.run([sys.executable,'-X','utf8',str(analysis),'--root',str(R),
            '--scoring',str(R/'scoring_001'),'--output',str(R/'analysis_001')],
            cwd=PROJECT,stdout=output,stderr=subprocess.STDOUT,check=True)
    save(R/'completion-pipeline-complete.json',dict(
        completed=True,execution='Explicit continuation after local Unicode delivery-failure closure and corrected clock-interval interpretation',
        original_controller_exit_codes_preserved=True,new_answer_requests_during_continuation=0,
        formal_protocol_sha256=sha(R/'protocol.json'),
        generation_audit_sha256=sha(R/'generation-audit.json'),
        scoring_completion_sha256=sha(R/'scoring_001/completion.json'),
        analysis_summary_sha256=sha(R/'analysis_001/summary.json'),
        local_delivery_closure_sha256=sha(R/'recovery/closure.json'),source_sha256=sha(source)))
    (R/'provenance/after-scoring-source.py').write_bytes(source.read_bytes())
    print('14B generation, scoring and preplanned statistics completed',flush=True)


if __name__=='__main__':main()
