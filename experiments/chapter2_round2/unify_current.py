"""Manage all existing Chapter2 results together, retaining exact run identities.

Only previously materialized copies move. Frozen original runs remain untouched.
No generation, scoring, tuning, or question authoring occurs here.
"""
from datetime import datetime, timezone
import argparse
from common import *
from split_existing200 import SPLIT, OUT, verify
from materialize_split import DATA_DIRS

SOURCES = {'8b': ('qwen3-8b', 'original'),
           '14b': ('qwen3-14b', 'original'),
           'round2_14b': ('qwen3-14b', 'replicate')}
METHODS = {
    'graph': ('完整来源图', 'main'), 'bm25': ('BM25', 'main'),
    'e5': ('E5 Dense', 'main'), 'hybrid': ('BM25+E5', 'main'),
    'bge_m3': ('BGE-M3 Dense', 'main'), 'bm25_bge_m3': ('BM25+BGE-M3', 'main'),
    'bm25_parent': ('BM25+父上下文', 'main'),
    'basic_search': ('基础搜索', 'main'), 'none': ('模型直接作答', 'main'),
    'graph_no_cross': ('去来源关联', 'ablation'),
    'graph_no_aliases': ('去中文别名', 'ablation'),
    'no_traversal': ('关闭关系遍历', 'ablation'),
    'anchor_only': ('仅交付锚点', 'ablation'),
}


def inside(path, root):
    path, root = path.resolve(), root.resolve()
    if path == root or not path.is_relative_to(root):
        raise ValueError('Unsafe migration path: ' + str(path))
    return path


def destination(model, part, run, tail):
    category, *remaining = Path(tail).parts
    if category == 'provenance':
        return CURRENT/model/part/category/run/Path(*remaining)
    arm, *remaining = remaining
    return CURRENT/model/part/category/arm/run/Path(*remaining)


def plan():
    verify()
    files, moves = {}, {}
    for old_model, (model, run) in SOURCES.items():
        for part in DATA_DIRS:
            root = OUT/old_model/part
            manifest = read(root/'physical-records.json')
            for relative, entry in manifest['files'].items():
                source = inside(OUT/relative, root)
                tail = source.relative_to(root)
                target = inside(destination(model, part, run, tail), CURRENT)
                key = target.relative_to(CURRENT).as_posix()
                if key in files:
                    raise ValueError('Conflicting unified record: ' + key)
                files[key] = dict(**entry, previous_copy=source.relative_to(WORKSPACE).as_posix(),
                                  model=model, role=part, run=run)
                pieces = tail.parts
                # Move whole arm directories; protocol files move individually.
                src = source if pieces[0] == 'provenance' else root/pieces[0]/pieces[1]
                dst = target if pieces[0] == 'provenance' else CURRENT/model/part/pieces[0]/pieces[1]/run
                moves[str(inside(src, root))] = str(inside(dst, CURRENT))
    if len(files) != 42243:
        raise ValueError('Unexpected copy population')
    return files, moves


def migrate():
    files, moves = plan()
    # Verify the entire operation before moving any directory. Resume safely if
    # an interruption occurred after an atomic rename.
    for rel, entry in files.items():
        src, dst = WORKSPACE/entry['previous_copy'], CURRENT/rel
        if src.is_file() and dst.exists():
            raise FileExistsError('Both old/new copies exist: ' + rel)
        current = src if src.is_file() else dst
        if not current.is_file() or current.is_symlink() or sha(current) != entry['sha256']:
            raise ValueError('Copy missing or changed: ' + rel)
        if sha(WORKSPACE/entry['source']) != entry['sha256']:
            raise ValueError('Frozen original changed: ' + entry['source'])
    for src_name, dst_name in moves.items():
        src, dst = Path(src_name), Path(dst_name)
        if src.exists():
            if dst.exists():
                raise FileExistsError('Migration target occupied: ' + str(dst))
            dst.parent.mkdir(parents=True, exist_ok=True)
            src.rename(dst)
        elif not dst.exists():
            raise FileNotFoundError('Migration source and target missing')
    for rel, entry in files.items():
        if sha(CURRENT/rel) != entry['sha256']:
            raise ValueError('Migrated record changed: ' + rel)
    migration = dict(schema='unified_physical_records_v1',
                     completed_utc=datetime.now(timezone.utc).isoformat(),
                     copied_files=len(files), files=files, split_sha256=sha(SPLIT),
                     policy='Move previously verified copies only; frozen original bytes, run IDs, scores and question roles unchanged.',
                     script_sha256=sha(Path(__file__)))
    save(CURRENT/'physical-records.json', migration)
    for old_model, (model, run) in SOURCES.items():
        for part in DATA_DIRS:
            old = OUT/old_model/part
            save(old/'layout-migration.json', dict(
                schema='physical_layout_redirect_v1',
                destination=(CURRENT/model/part).relative_to(WORKSPACE).as_posix(),
                run=run, manifest=(CURRENT/'physical-records.json').relative_to(WORKSPACE).as_posix(),
                original_copy_manifest_retained=True))
            (old/'README.md').write_text(
                '# 历史分集统计快照\n\n问答实体已统一迁入`current/'+model+'/'+part+
                '/`，按方法/original或replicate/题目ID管理。此处只保留此前分集统计、旧复制清单和layout-migration.json，'
                '不再作为当前问答目录。原始全量回执与评分未改。\n', encoding='utf-8')
    print('Unified actual QA records; verified files:', len(files), flush=True)


def publish():
    split = verify()
    physical = read(CURRENT/'physical-records.json')
    catalog = dict(schema='chapter2_unified_results_v1',
                   updated_utc=datetime.now(timezone.utc).isoformat(),
                   development_questions=160, test_questions=40,
                   test_groups=5, test_types=split['test']['types'],
                   split_sha256=sha(SPLIT), sessions=4600,
                   datasets={k:v.relative_to(WORKSPACE).as_posix() for k,v in DATA_DIRS.items()},
                   physical_manifest_sha256=sha(CURRENT/'physical-records.json'),
                   methods={k:dict(name=v[0],family=v[1]) for k,v in METHODS.items()},
                   models={}, sources={},
                   presentation='One main comparison includes E5 and BGE-M3; graph/BM25 original and replicate remain separate rows, per user confirmation.',
                   inference='Preserve historical within-protocol5+2 and replicate4+2 comparison families; no cross-protocol confirmatory tests, pooling or score selection.',
                   human_review=dict(judge_calibration='pending',graph_quality='pending',
                                     user_confirmed_pending=True),
                   no_new_api_calls=True)
    for model in ['qwen3-8b','qwen3-14b']:
        catalog['models'][model]={}
        source_keys=[k for k,v in SOURCES.items() if v[0]==model]
        for part in DATA_DIRS:
            target=CURRENT/model/part; rows=[]; summaries={}; inputs={}
            for key in source_keys:
                run=SOURCES[key][1]; origin=OUT/key/part
                summaries[run]=read(origin/'summary.json')
                original_rows=read(origin/'session-metrics.json')
                for row in original_rows:
                    rows.append(dict(method=row['arm'],run=run,record=row,
                                     generation=f"generation/{row['arm']}/{run}/{row['id']}/result.json",
                                     scoring=f"scoring/{row['arm']}/{run}/{row['id']}/result.json"))
                for name in ['summary.json','session-metrics.json']:
                    p=origin/name; inputs[p.relative_to(WORKSPACE).as_posix()]=sha(p)
            ids=set(split[part]['ids'])
            if any(r['record']['id'] not in ids for r in rows):raise ValueError('Mixed subset')
            if len(rows)!=len({(r['run'],r['method'],r['record']['id'])for r in rows}):raise ValueError('Duplicate session identity')
            summary=dict(schema='unified_run_preserving_summary_v1',model=model,role=part,
                         question_count=len(ids),sessions=len(rows),by_run=summaries,
                         source_sha256=inputs,split_sha256=sha(SPLIT),
                         original_scores_unchanged=True,run_averaging=False)
            save(target/'summary.json',summary)
            save(target/'session-metrics.json',rows)
            local={k:v for k,v in physical['files'].items() if k.startswith(f'{model}/{part}/')}
            save(target/'physical-records.json',dict(schema='unified_subset_records_v1',
                model=model,role=part,questions=len(ids),sessions=len(rows),files=local,
                root='current/',copied_files=len(local)))
            (target/'README.md').write_text(
                '# '+model+' / '+part+'\n\n本目录包含'+str(len(ids))+'题、'+str(len(rows))+
                '个既有会话。generation/、scoring/和scoring_payloads/按方法/original或replicate/问题ID组织。'
                'E5与BGE-M3均保留；完整图和BM25的两次运行不平均、不择优。summary.json统一管理各运行统计；'
                'session-metrics.json中record逐对象保留原评分行，其余字段仅用于定位来源。实体文件来源与哈希见physical-records.json。'
                '开发与测试目录互不混入题目，Gold仍只在题集scoring/侧。\n',encoding='utf-8')
            catalog['models'][model][part]=dict(path=target.relative_to(WORKSPACE).as_posix(),
                questions=len(ids),sessions=len(rows),runs=list(summaries),
                summary_sha256=sha(target/'summary.json'),rows_sha256=sha(target/'session-metrics.json'))
    for key,(model,run)in SOURCES.items():
        catalog['sources'][key]=dict(model=model,run=run,path=(OUT/key).relative_to(WORKSPACE).as_posix(),
            original_row_binding=read(OUT/key/'binding.json'))
    save(CURRENT/'results.json',catalog)
    print('Unified catalog:9 main methods,4 ablations;4600 exact scored records',flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['migrate','publish'])
    a=p.parse_args();migrate()if a.action=='migrate'else publish()
