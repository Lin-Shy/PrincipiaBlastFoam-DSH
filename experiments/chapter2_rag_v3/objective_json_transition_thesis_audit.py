"""Check manuscript numbers and official PDF against the transition snapshot."""
from pathlib import Path
import objective_experiment as exp
import objective_json_transition as transition
import figure_style as style


def main():
    out = transition.OUT
    snap_path = out/'results/snapshot.json'; snap = exp.read(snap_path)
    audit = exp.read(out/'results/json_audit.json')
    if audit['status']!='passed' or audit['snapshot_sha256']!=exp.sha(snap_path):
        raise ValueError('Snapshot audit mismatch')
    root = exp.WORK/'graduation-thesis-materials/graduation-manuscript'
    assets = root/'assets'; lines = (assets/'objective_metrics.tex').read_text(encoding='utf8').splitlines()
    for model in ('qwen3-8b','qwen3-14b'):
        for method,name in style.NAMES.items():
            row=next(r for r in snap['configurations'] if r['model']==model and r['method']==method)
            fields=[row[k] for k in ('accuracy','fill_accuracy','short_accuracy','single_accuracy','judge_accuracy')]
            expected=model.replace('-','\\mbox{-}')+' & '+name+' & '+str(row['completed'])+'/'+str(row['planned'])+' & '+' & '.join(f'{x*100:.1f}' for x in fields)+r' \\'
            if lines.count(expected)!=1:raise ValueError('Table mismatch '+model+' '+method)
    body=(root/'docs/chap02_objective_results.tex').read_text(encoding='utf8')
    for model,label in [('qwen3-8b','8B'),('qwen3-14b','14B')]:
        graph=next(r for r in snap['configurations'] if r['model']==model and r['method']=='graph')
        bm=next(r for r in snap['configurations'] if r['model']==model and r['method']=='bm25')
        pair=next(r for r in snap['statistics']['paired'] if r['model']==model and r['comparison']=='bm25')
        expected=f'{label}完整图与BM25准确率分别为{100*graph["accuracy"]:.2f}\\%和{100*bm["accuracy"]:.2f}\\%'
        if expected not in body or f'p={pair["holm_p"]:.4f}' not in body:raise ValueError('Narrative mismatch '+model)
    if '649项' not in body or '7项' not in body:raise ValueError('Outage limitations missing')
    official=exp.read(root/'official_manifest.json')
    if official['pdf_sha256']!=exp.sha(root/'main.pdf') or official.get('review',{}).get('result')!='passed':
        raise ValueError('PDF hash or visual review missing')
    changed=[rel for rel,digest in official['source_files_sha256'].items() if not (root/rel).is_file() or exp.sha(root/rel)!=digest]
    if changed:raise ValueError('Official PDF source drift: '+str(changed[:4]))
    exp.save(out/'analysis/thesis_audit.json',dict(status='passed',table_rows=26,snapshot_sha256=exp.sha(snap_path),
        pdf_sha256=exp.sha(root/'main.pdf'),official_manifest_sha256=exp.sha(root/'official_manifest.json'),
        source_files_checked=len(official['source_files_sha256']),audit_code_sha256=exp.sha(Path(__file__)),
        note='PDF includes the current worktree, including pre-existing uncommitted edits.'))
    print('Transition thesis audit passed: 26 table rows,',len(official['source_files_sha256']),'sources')


if __name__=='__main__':main()
