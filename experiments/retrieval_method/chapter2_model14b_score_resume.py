"""Continue once after local delivery closure; never issue answer requests."""
from pathlib import Path
import subprocess
import sys
from chapter2_optimization_200 import PROJECT, read, save, sha
from chapter2_publication_200 import verify


def main(root):
    p=verify(root)
    assert p['answer_model']=='qwen3-14b'
    auth=read(root/'user-authorization.json')
    assert auth['explicit_data_export_approved'] and auth['generation_and_scoring_export']
    closure=read(root/'recovery/closure.json')
    assert closure['network_calls']==closure['answer_text_repairs']==0
    assert len(closure['recovered_sessions'])==2
    assert read(root/'generation-controller-completion.json')['complete']
    assert not (root/'scoring_001').exists()
    source=Path(__file__)
    analysis=source.with_name('chapter2_model14b_analysis_200.py')
    old=read(root/'completion-pipeline-protocol.json')
    assert sha(analysis)==old['analysis_source_sha256']
    save(root/'score-continuation-protocol.json',dict(
        source_sha256=sha(source),generation_protocol_sha256=sha(root/'protocol.json'),
        local_delivery_closure_sha256=sha(root/'recovery/closure.json'),
        analysis_source_sha256=sha(analysis),new_answer_requests=0,
        rubric_unchanged=True,judge='qwen3-14b',judge_workers=16,
        rule='Two invalid Unicode outputs count as generation failures, not repaired answers; retain all original receipts. Original generation/metric protocol unchanged.'))
    (root/'provenance/score-continuation-source.py').write_bytes(source.read_bytes())
    script=source.parent
    def run(name,log,*args):
        with (root/'logs'/log).open('x',encoding='utf-8') as out:
            subprocess.run([sys.executable,'-X','utf8',str(script/(name+'.py')),*map(str,args)],
                cwd=PROJECT,stdout=out,stderr=subprocess.STDOUT,check=True)
        print('completed',name,flush=True)
    run('chapter2_model14b_generation_audit','generation-audit.log','--root',root,'--final')
    run('chapter2_formal_scoring_200','scoring-prepare.log','prepare','--root',root,'--output',root/'scoring_001')
    run('chapter2_formal_scoring_200','scoring-run.log','run','--root',root,'--output',root/'scoring_001')
    run('chapter2_model14b_analysis_200','analysis.log','--root',root,'--scoring',root/'scoring_001','--output',root/'analysis_001')
    save(root/'completion-pipeline-complete.json',dict(
        formal_protocol_sha256=sha(root/'protocol.json'),generation_audit_sha256=sha(root/'generation-audit.json'),
        scoring_completion_sha256=sha(root/'scoring_001/completion.json'),
        analysis_summary_sha256=sha(root/'analysis_001/summary.json'),completed=True,
        score_continuation_protocol_sha256=sha(root/'score-continuation-protocol.json')))
    print('14B scoring and analysis complete',flush=True)


if __name__=='__main__':
    main(PROJECT.parent/'graduation-experiment-results/chapter2_retrieval/current/model14b_200_20261019_002')
