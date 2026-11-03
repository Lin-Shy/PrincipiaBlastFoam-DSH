"""Verify manuscript and reviewed PDF against post-hoc recovery results."""
from pathlib import Path
import objective_experiment as exp
import objective_json_failure_rerun as run
import figure_style as style


def main():
    out=run.OUT;snapshot=out/'results/snapshot.json';snap=exp.read(snapshot);audit=exp.read(out/'results/json_audit.json')
    if audit['status']!='passed' or audit['snapshot_sha256']!=exp.sha(snapshot):raise ValueError('Snapshot audit mismatch')
    root=exp.WORK/'graduation-thesis-materials/graduation-manuscript'
    table=(root/'assets/objective_metrics.tex').read_text(encoding='utf8').splitlines()
    for model in ('qwen3-8b','qwen3-14b'):
        for method,name in style.NAMES.items():
            row=next(x for x in snap['configurations'] if x['model']==model and x['method']==method)
            nums=[row[k] for k in ('accuracy','fill_accuracy','short_accuracy','single_accuracy','judge_accuracy')]
            expected=model.replace('-','\\mbox{-}')+' & '+name+' & '+str(row['completed'])+'/'+str(row['planned'])+' & '+' & '.join(f'{x*100:.1f}' for x in nums)+r' \\'
            if table.count(expected)!=1:raise ValueError('Table row mismatch '+model+' '+method)
    body=(root/'docs/chap02_objective_results.tex').read_text(encoding='utf8')
    if f'{audit["rerun"]}项生成失败' not in body or f'{audit["rerun_answered"]}份回答' not in body:
        raise ValueError('Recovery caveat mismatch')
    for model,label in [('qwen3-8b','8B'),('qwen3-14b','14B')]:
        g=next(x for x in snap['configurations'] if x['model']==model and x['method']=='graph')
        b=next(x for x in snap['configurations'] if x['model']==model and x['method']=='bm25')
        p=next(x for x in snap['statistics']['paired'] if x['model']==model and x['comparison']=='bm25')
        if f'{label}完整图与BM25准确率分别为{100*g["accuracy"]:.2f}\\%和{100*b["accuracy"]:.2f}\\%' not in body or f'p={p["holm_p"]:.4f}' not in body:raise ValueError('Narrative mismatch '+model)
    official=exp.read(root/'official_manifest.json')
    if official['pdf_sha256']!=exp.sha(root/'main.pdf') or official.get('review',{}).get('result')!='passed':raise ValueError('PDF review mismatch')
    changed=[k for k,v in official['source_files_sha256'].items() if not (root/k).is_file() or exp.sha(root/k)!=v]
    if changed:raise ValueError('PDF source mismatch '+str(changed[:4]))
    exp.save(out/'analysis/thesis_audit.json',dict(status='passed',table_rows=26,snapshot_sha256=exp.sha(snapshot),
        pdf_sha256=exp.sha(root/'main.pdf'),official_manifest_sha256=exp.sha(root/'official_manifest.json'),
        source_files_checked=len(official['source_files_sha256']),audit_code_sha256=exp.sha(Path(__file__)),
        note='PDF was compiled from the current worktree, including pre-existing uncommitted source edits.'))
    print('Failure recovery thesis audit passed: 26 rows')


if __name__=='__main__':main()
