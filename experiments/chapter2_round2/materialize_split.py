"""Physical160/40 directories; copy exact existing data/receipts, never hardlink."""
import argparse
from datetime import datetime,timezone
import shutil
from common import *
from split_existing200 import SPLIT,OUT,verify

DATA_DIRS=dict(development=DATASET.parent/'development_v1_160',test=DATASET.parent/'test_v1_40')

def datasets():
    p=verify();qs=public_questions();anns=read(DATASET/'scoring/annotations.json');ev=read(DATASET/'scoring/evidence.json')
    for name,target in DATA_DIRS.items():
        if target.exists():raise FileExistsError('physical dataset already exists')
        ids=set(p[name]['ids']);public=[q for q in qs if q['id']in ids];a=[r for r in anns if r['id']in ids];eids={e for r in a for e in r['required_evidence_ids']};e={k:v for k,v in ev.items()if k in eids}
        save(target/'model/questions.json',public);save(target/'scoring/annotations.json',a);save(target/'scoring/evidence.json',e)
        save(target/'dataset.json',dict(schema='existing200_physical_subset_v1',role=name,questions=len(public),source_dataset='formal_v2_200',source_ids=p[name]['ids'],
            types=p[name]['types'],themes=p[name]['themes'],knowledge_groups=p[name]['knowledge_groups'],split_sha256=sha(SPLIT),
            researcher_confirmation=p['researcher_confirmation'],created_from_existing_objects_only=True,new_questions=0,new_scoring_labels=0,
            model_input='model/questions.json only; annotations/evidence remain scoring-side'))
        save(target/'binding.json',dict(source_sha256=p['source_sha256'],split_sha256=sha(SPLIT),files_sha256={f.relative_to(target).as_posix():sha(f)for f in target.rglob('*.json')},script_sha256=sha(Path(__file__))))
        lines=['# '+('160题开发与调参集'if name=='development'else'40题未见留出测试集'),'',
            '直接从原formal_v2_200按既有题目身份复制；没有新构造题目、改写自然问题、改必要点或改评分。模型仅接收model/questions.json。评分侧文件单独存放，不进入构图/检索/生成。',
            '研究者2026-10-20更正未同步调参记录，确认原160题用于调参，原40题未参与调参；本目录和划分记录不回写原执行日期。','',
            '题目ID、自然问题、标注对象与原件逐项相等；文件级绑定见binding.json。','']
        lines += [f"## {q['id']}\n\n{q['question']}\n"for q in public]
        (target/'questions.md').write_text('\n'.join(lines),encoding='utf-8')
        (target/'README.md').write_text('\n'.join(lines[:6])+'\n\n[逐题清单](questions.md)\n',encoding='utf-8')
        print('Physical dataset:',name,len(public),flush=True)

def locations(model,arm):
    if model=='round2_14b':
        base=ARCHIVE/'e2e_runs/answer14b_003'
        return base/arm/'generation',base/'scoring_001',[(ARCHIVE/'configs/e2e_14b_v1.json'),(ARCHIVE/'configs/scoring_14b_v1.json'),(ARCHIVE/'configs/scoring_continuation_v2.json')]
    basic=CURRENT/'basic_search_200_20261019_001'/('qwen3-'+model)
    if arm=='basic_search':return basic/'generation'/arm,basic/'scoring_001',[basic/'protocol.json',basic/'scoring_001/protocol.json']
    base=CURRENT/('revision_200_20261019_002'if model=='8b'else'model14b_200_20261019_002')
    if model=='8b'and arm in ['bm25','e5','hybrid','none']:
        return base/'reused/generation'/arm,base/'reused/scoring',[base/'reused/protocol.json']
    return base/'generation'/arm,base/'scoring_001',[base/'protocol.json',base/'scoring_001/protocol.json']

def copy_file(source,target,bindings):
    if not source.is_file():raise FileNotFoundError('original record missing: '+str(source))
    if target.exists():raise FileExistsError('physical record already exists: '+str(target))
    target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
    h=sha(source)
    if sha(target)!=h:raise ValueError('copied raw record differs')
    bindings[target.relative_to(OUT).as_posix()]=dict(source=source.relative_to(WORKSPACE).as_posix(),sha256=h)

def records():
    p=verify()
    for model in ['8b','14b','round2_14b']:
        for part in DATA_DIRS:
            target=OUT/model/part
            if(target/'physical-records.json').exists():raise FileExistsError('closed physical copy already exists')
            rows=read(target/'session-metrics.json');ids=set(p[part]['ids']);bindings={};protocols=set()
            if any(r['id']not in ids for r in rows):raise ValueError('mixed subset metrics')
            for row in rows:
                arm=row['arm'];qid=row['id'];generation,scoring,ps=locations(model,arm);protocols.update(ps)
                for category,folder in [('generation',generation/qid),('scoring',scoring/'sessions'/arm/qid)]:
                    if not(folder/'result.json').exists():raise FileNotFoundError('missing original final record: '+str(folder))
                    for source in sorted(folder.rglob('*')):
                        if source.is_file():copy_file(source,target/category/arm/qid/source.relative_to(folder),bindings)
                payload=scoring/'payloads'/arm/(qid+'.json')
                if payload.exists():copy_file(payload,target/'scoring_payloads'/arm/payload.name,bindings)
            for source in sorted(protocols):copy_file(source,target/'provenance'/(source.parent.name+'_'+sha(source)[:12]+'_'+source.name),bindings)
            save(target/'physical-records.json',dict(schema='physical_split_records_v1',role=part,model=model,questions=len(ids),sessions=len(rows),
                split_sha256=sha(SPLIT),dataset_dir=str(DATA_DIRS[part].relative_to(WORKSPACE)),copied_files=len(bindings),files=bindings,
                copy_policy='Real files, byte-exact copies; no symlinks/hardlinks; original all200 retained read-only. Generation and scoring separate.',
                script_sha256=sha(Path(__file__)),completed_utc=datetime.now(timezone.utc).isoformat()))
            (target/'README.md').write_text('# '+model+' / '+part+'\n\n本目录只含此子集的原始generation/、scoring/、scoring_payloads/和派生session-metrics/summary；按方法与问题ID显式分开。provenance/保留原全量批次协议及其身份，不将协议的全量计数当作本子集会话。所有真实文件均逐字节核对，见physical-records.json。\n',encoding='utf-8')
            print('Copied physical QA:',model,part,len(ids),'questions',len(rows),'sessions',len(bindings),'files',flush=True)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('action',choices=['datasets','records']);a=ap.parse_args();datasets()if a.action=='datasets'else records()
