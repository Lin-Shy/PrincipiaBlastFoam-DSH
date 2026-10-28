"""Hash inventory, reversible report consolidation and in-place evidence archive.

Frozen experiment trees are never moved. No raw evidence is deleted.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import stat
import zipfile
import single_pass_dev40 as s

ROOT=Path('\\\\?\\'+str(s.RUN.resolve())) if os.name=='nt' else s.RUN
ARCHIVE=ROOT/'00_archive'
INVENTORY=ARCHIVE/'asset_inventory.json'
HISTORY={
 '02_judge_calibration':'Historical calibration and manual originals; later fixed scoring protocol is in scoring/',
 'experiments/agentic/reused_inputs':'Historical generation; 120 answers reused by explicit hash mapping; runtime snapshot remains authoritative',
 '05_api_preparation_20261022_v1':'Historical provider preparation',
 '06_unified_api_execution_20261022_v1':'Historical provider execution',
 '07_continuous_execution_20261022_v1':'Historical continuation/evidence exports',
 '08_ai_cross_calibration_20261022_v1':'Historical prompt development; no use for new parameter selection',
 '09_dual_judge_sol_flash_20261023_v1':'Historical dual-judge calibration',
 '10_human_ui_v2_20261023':'Historical human UI/exports; manual labels preserved',
 '11_human_import_dual_calibration_20261024_v1':'Historical human import and audit preparation',
 'active_execution_requests':'Historical request evidence; immutable request identity',
}


def hashfile(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for chunk in iter(lambda:f.read(1048576),b''):h.update(chunk)
    return h.hexdigest()


def files():
    for folder,dirs,names in os.walk(ROOT,followlinks=False):
        for name in names:
            p=Path(folder)/name
            if p.is_symlink():continue
            yield p


def inventory():
    if INVENTORY.exists():return s.load(INVENTORY)
    paths=[p for p in files() if '/recovery/' not in p.as_posix()
           and not p.name.endswith('.lock') and p.suffix!='.pyc'
           and 'retrieval_study' not in p.parts
           and p.name not in ('resolution.json','recovery_preflight.json','recovery_ledger.jsonl','recovery_events.jsonl','recovery_summary.json')]
    def record(p):
        rel=p.relative_to(ROOT).as_posix()
        archive=next((k for k in HISTORY if rel==k or rel.startswith(k+'/')),None)
        return dict(path=rel,sha256=hashfile(p),bytes=p.stat().st_size,
                    state='archived_in_place' if archive else 'active_or_formal_evidence')
    with ThreadPoolExecutor(max_workers=8) as pool:rows=list(pool.map(record,paths))
    result=dict(schema='chapter2_asset_inventory',created_utc=s.now(),files=rows,
        file_count=len(rows),bytes=sum(x['bytes'] for x in rows),
        protection='All pre-existing evidence stays in place; historical states are logical archive classifications',
        exclusions='New in-flight bounded recovery records, regeneration caches, this finalization study')
    s.save(INVENTORY,result)
    print(json.dumps(dict(inventoried=len(rows),bytes=result['bytes'])),flush=True)
    return result


def archive_docs():
    data=inventory()
    targets={'README.offline_before_scheme_b.md':'00_archive/reports/offline_before_scheme_b.md',
             'REPRODUCE.md':'00_archive/reports/offline_reproduce.md',
             'single_pass_dev40_v1/STATUS.md':'00_archive/reports/single_pass_before_finalization.md'}
    mappingfile=ARCHIVE/'report_migration.json'
    mapping=s.load(mappingfile) if mappingfile.exists() else dict(schema='lossless_report_consolidation',moves=[])
    hashes={r['path']:r['sha256'] for r in data['files']}
    for old,new in targets.items():
        source=ROOT/old;target=ROOT/new
        if not source.exists():continue
        assert hashfile(source)==hashes[old]
        assert not target.exists()
        target.parent.mkdir(parents=True,exist_ok=True)
        # Explicitly verified workspace-contained paths; reversible rename only.
        assert source.resolve().is_relative_to(ROOT.resolve()) and target.resolve().is_relative_to(ROOT.resolve())
        source.rename(target)
        assert hashfile(target)==hashes[old]
        mapping['moves'].append(dict(old=old,new=new,sha256=hashes[old]))
        s.save(mappingfile,mapping)
    # Preserve root entry before editing it; map old bytes to the archived copy.
    target=ARCHIVE/'reports/root_readme_before_finalization.md'
    if not target.exists():
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes((ROOT/'README.md').read_bytes())
        mapping['root_readme_history']=dict(old='README.md',new=target.relative_to(ROOT).as_posix(),sha256=hashfile(target))
        s.save(mappingfile,mapping)
    return mapping


def clean_cache():
    inventory()
    receiptfile=ARCHIVE/'cache_cleanup.json'
    if receiptfile.exists():return s.load(receiptfile)
    candidates=[p for p in files() if p.suffix=='.pyc' and '__pycache__' in p.parts]
    dest=ARCHIVE/'rebuildable_python_cache.zip'
    receipt=dict(created_utc=s.now(),cache_files=[],irreversible_deletions=0)
    if candidates:
        with zipfile.ZipFile(dest,'x',compression=zipfile.ZIP_DEFLATED) as z:
            for p in candidates:
                rel=p.relative_to(ROOT).as_posix();content=p.read_bytes()
                z.writestr(rel,content)
                receipt['cache_files'].append(dict(path=rel,sha256=hashlib.sha256(content).hexdigest(),bytes=len(content)))
        with zipfile.ZipFile(dest) as z:
            for row in receipt['cache_files']:
                assert hashlib.sha256(z.read(row['path'])).hexdigest()==row['sha256']
        for p in candidates:
            assert p.resolve().is_relative_to(ROOT.resolve()) and p.suffix=='.pyc'
            p.unlink()
        receipt['archive_sha256']=hashfile(dest)
    s.save(receiptfile,receipt)
    return receipt


def verify():
    data=s.load(INVENTORY)
    migration=s.load(ARCHIVE/'report_migration.json') if (ARCHIVE/'report_migration.json').exists() else {}
    moves={r['old']:r['new'] for r in migration.get('moves',[])}
    if 'root_readme_history' in migration:
        r=migration['root_readme_history'];moves[r['old']]=r['new']
    def check(row):
        p=ROOT/moves.get(row['path'],row['path'])
        if not p.exists():return dict(path=row['path'],status='missing')
        if hashfile(p)!=row['sha256']:return dict(path=row['path'],status='changed')
    with ThreadPoolExecutor(max_workers=8) as pool:
        problems=[v for v in pool.map(check,data['files']) if v]
    result=dict(checked_utc=s.now(),files_checked=len(data['files']),problems=problems,
                evidence_intact=not problems,report_moves=moves,inventory_sha256=hashfile(INVENTORY))
    s.save(ARCHIVE/'asset_verification.json',result)
    print(json.dumps(result,ensure_ascii=False),flush=True)
    return result


def catalog():
    data=inventory();groups=[]
    for path,meaning in HISTORY.items():
        rows=[r for r in data['files'] if r['path'].startswith(path+'/')]
        groups.append(dict(path=path,state='archived_in_place',purpose=meaning,
                           files=len(rows),bytes=sum(r['bytes'] for r in rows),moved=False))
    obj=dict(updated_utc=s.now(),historical=groups,
        active=['data','experiments/agentic/dev40','experiments/single_pass/dev40','scoring','finalization'],
        dependencies=dict(Agentic_reuse='experiments/agentic/dev40/reuse.json',
                          judge_audit='scoring/audit/results/acceptance.json',
                          resources='../resources',legacy_200='00_archive/archive_receipt.json'),
        rule='Immutable raw evidence/frozen manifests remain at their bound paths; archive views hide historical development from active navigation',
        deferred='48 unexecuted budget variants remain in the original candidate matrix; never represented as completed')
    s.save(ARCHIVE/'catalog.json',obj)
    html='<!doctype html><meta charset="utf-8"><title>第2章历史资产</title><style>body{font:16px system-ui;max-width:1100px;margin:40px auto}td,th{padding:10px;border-bottom:1px solid #ddd;text-align:left}</style><h1>历史资产归档</h1><p><a href="../README.md">当前总入口</a> · <a href="asset_verification.json">哈希核验</a> · <a href="report_migration.json">说明迁移映射</a></p><p>历史原件按原路径就地归档，保留绝对路径、Manifest及SHA256依赖。只读属性不是WORM或外部备份。</p><table><tr><th>目录</th><th>用途</th><th>文件</th></tr>'
    for row in groups:html+=f'<tr><td><a href="../{row["path"]}/">{row["path"]}</a></td><td>{row["purpose"]}</td><td>{row["files"]}</td></tr>'
    html+='</table>'
    (ARCHIVE/'index.html').write_text(html,encoding='utf-8')
    return obj


def seal():
    data=s.load(INVENTORY);count=0
    for row in data['files']:
        if row['state']!='archived_in_place' and not row['path'].startswith(('data/','scoring/audit/')):
            continue
        p=ROOT/row['path']
        assert hashfile(p)==row['sha256']
        p.chmod(p.stat().st_mode & ~stat.S_IWRITE)
        count+=1
    receipt=dict(created_utc=s.now(),files_sealed=count,bytes_unchanged=True,
                 mechanism='Windows read-only file attribute; not ACL/WORM or offsite backup',
                 historical_trees_moved=False)
    s.save(ARCHIVE/'in_place_seal.json',receipt)
    print(json.dumps(receipt))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('command',choices=['inventory','archive-docs','cache','verify','catalog','seal']);a=p.parse_args()
    {'inventory':inventory,'archive-docs':archive_docs,'cache':clean_cache,'verify':verify,'catalog':catalog,'seal':seal}[a.command]()
