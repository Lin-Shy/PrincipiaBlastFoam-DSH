"""Audit objective thesis tables, figure bindings and PDF source manifest."""
from pathlib import Path
import objective_experiment as exp
import figure_style as style

def main():
    strict_path=exp.OUT/'results/snapshot.json';supp_path=exp.OUT/'supplementary_parser/results/snapshot.json'
    strict=exp.read(strict_path);supp=exp.read(supp_path)
    if strict['status']!='closed' or supp['status']!='closed' or strict['manifest_sha256']!=supp['manifest_sha256']:
        raise ValueError('two aligned closed snapshots required')
    root=exp.WORK/'graduation-thesis-materials/graduation-manuscript';assets=root/'assets'
    table=(assets/'objective_metrics.tex').read_text(encoding='utf8').splitlines()
    comparison=(assets/'objective_parsing_comparison.tex').read_text(encoding='utf8').splitlines()
    for model in ('qwen3-8b','qwen3-14b'):
        for method,name in style.NAMES.items():
            row=next(x for x in strict['configurations'] if x['model']==model and x['method']==method)
            alt=next(x for x in supp['configurations'] if x['model']==model and x['method']==method)
            fields=[row[k] for k in ('accuracy','fill_accuracy','short_accuracy','single_accuracy','judge_accuracy')]
            expected=model.replace('-','\\mbox{-}')+' & '+name+' & '+str(row['completed'])+'/'+str(row['planned'])+' & '+' & '.join(f'{x*100:.1f}' for x in fields)+r' \\'
            expected_alt=model.replace('-','\\mbox{-}')+' & '+name+f" & {row['accuracy']*100:.1f} & {alt['accuracy']*100:.1f}"+r' \\'
            if table.count(expected)!=1 or comparison.count(expected_alt)!=1:raise ValueError('table mismatch '+model+' '+method)
    asset_prov=exp.read(exp.OUT/'results/objective_assets_provenance.json')
    if asset_prov['snapshot_sha256']!=exp.sha(strict_path) or asset_prov['supplementary_snapshot_sha256']!=exp.sha(supp_path):
        raise ValueError('asset snapshots mismatch')
    for key,path in [('figure_sha256',assets/'objective_main_accuracy.pdf'),('table_sha256',assets/'objective_metrics.tex'),('parsing_table_sha256',assets/'objective_parsing_comparison.tex')]:
        if asset_prov[key]!=exp.sha(path):raise ValueError('asset hash mismatch '+key)
    insert=root/'docs/chap02_objective_results.tex';man_prov=exp.read(exp.OUT/'results/objective_manuscript_provenance.json')
    if man_prov['insert_sha256']!=exp.sha(insert) or man_prov['strict_snapshot_sha256']!=exp.sha(strict_path) or man_prov['supplementary_snapshot_sha256']!=exp.sha(supp_path):
        raise ValueError('manuscript insert provenance mismatch')
    text=insert.read_text(encoding='utf8')
    for model,label in [('qwen3-8b','8B'),('qwen3-14b','14B')]:
        graph=next(x for x in strict['configurations'] if x['model']==model and x['method']=='graph')
        bm=next(x for x in strict['configurations'] if x['model']==model and x['method']=='bm25')
        pair=next(x for x in strict['statistics']['paired'] if x['model']==model and x['comparison']=='bm25')
        expected=f'{label}完整图和BM25的冻结规则准确率分别为{100*graph["accuracy"]:.2f}\\%和{100*bm["accuracy"]:.2f}\\%'
        if expected not in text or f'p={pair["holm_p"]:.4f}' not in text:raise ValueError('narrative mismatch '+model)
    official=exp.read(root/'official_manifest.json')
    if official['pdf_sha256']!=exp.sha(root/'main.pdf') or official.get('review',{}).get('result')!='passed':
        raise ValueError('PDF or visual review mismatch')
    changed=[rel for rel,digest in official['source_files_sha256'].items() if not (root/rel).is_file() or exp.sha(root/rel)!=digest]
    if changed:raise ValueError('PDF source manifest mismatch '+str(changed[:4]))
    out={'status':'passed','table_rows_per_table':26,'strict_snapshot_sha256':exp.sha(strict_path),
         'supplementary_snapshot_sha256':exp.sha(supp_path),'pdf_sha256':exp.sha(root/'main.pdf'),
         'official_manifest_sha256':exp.sha(root/'official_manifest.json'),'source_files_checked':len(official['source_files_sha256']),
         'note':'PDF compiled from the recorded current worktree, including pre-existing uncommitted source changes.',
         'audit_code_sha256':exp.sha(Path(__file__))}
    exp.save(exp.OUT/'analysis/thesis_audit.json',out)
    print('thesis table and PDF provenance audit passed: 52 table rows,',len(official['source_files_sha256']),'source files')

if __name__=='__main__':main()
