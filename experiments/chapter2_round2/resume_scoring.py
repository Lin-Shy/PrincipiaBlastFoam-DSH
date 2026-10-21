"""Offline canonical closure and paid score continuation; never resend closed work.

Original002 files stay immutable. Reuse closed1000 scores byte for byte. The
only changed generation representation is an answered result with a lone
surrogate: retain original and classify invalid_unicode_output (failure0).
This applies to every arm/question, before any new scoring.
"""
import argparse
from collections import Counter
import shutil
import time
from common import *
import score_round2 as scorer
from resume_generation import safe_save

OLD=ARCHIVE/'e2e_runs/answer14b_002'
NEW=ARCHIVE/'e2e_runs/answer14b_003'
PROTOCOL=ARCHIVE/'configs/scoring_continuation_v2.json'
APPROVAL=ARCHIVE/'authorizations/scoring14b_002_explicit_export.json'

def invalid_unicode(r):
    if r['status']!='answered':return False
    try:
        json.dumps(dict(answer=r['answer'],references=r['references']),ensure_ascii=False).encode('utf-8')
    except UnicodeEncodeError:return True
    return False

def copy_arm(arm):
    source=OLD/arm;target=NEW/arm
    completed=read(source/'completed.json');changed=[]
    if completed['questions']!=200:raise ValueError('incomplete generation arm')
    shutil.copytree(source,target)
    for qid,h in completed['results_sha256'].items():
        src=source/'generation'/qid/'result.json';dst=target/'generation'/qid/'result.json'
        if sha(src)!=h or sha(dst)!=h:raise ValueError('source generation drift')
        r=read(src)
        if invalid_unicode(r):
            dst.rename(dst.with_name('original_result.json'))
            r.update(status='invalid_unicode_output',answer=None,references=None,references_delivered=False)
            safe_save(dst,r);changed.append(dict(id=qid,original_sha256=h,canonical_sha256=sha(dst),policy='invalid_unicode_output; failure0; no correction or API retry'))
    if changed:
        (target/'completed.json').rename(target/'original_completed.json')
        completed.update(statuses=dict(Counter(read(p)['status']for p in (target/'generation').glob('*/result.json'))),
            results_sha256={qid:sha(target/'generation'/qid/'result.json')for qid in completed['results_sha256']})
        safe_save(target/'completed.json',completed)
    safe_save(NEW/'canonical_closures'/(arm+'.json'),dict(original_completion_sha256=sha(source/'completed.json'),changes=changed,
        requests_replayed=0,rule='All answered outputs must serialize as valid UTF8; no method-specific exception'))

def prepare():
    p=scorer.verify(APPROVAL)
    if NEW.exists()or PROTOCOL.exists():raise FileExistsError('fresh continuation required')
    closed=[a for a in p['arms']if(OLD/'scoring_001/completed_arms'/(a+'.json')).exists()]
    if len(closed)!=5:raise ValueError('expected exactly5 closed scoring arms; audit before changing this continuation')
    safe_save(PROTOCOL,dict(schema='round2_unicode_score_continuation_v2',original_generation=str(OLD),canonical_generation=str(NEW),
        scoring_protocol_sha256=sha(scorer.CONFIG),original_approval_sha256=sha(APPROVAL),
        source_sha256=sha(Path(__file__)),safe_writer_sha256=sha(HERE/'resume_generation.py'),
        reused_arms=closed,reused_sessions=1000,new_sessions=400,
        change='ASCIIescaped lossless disk serialization; valid UTF8 delivery check on all7 arms. Lone surrogate =>invalid_unicode_output, failure0. No replacement, repair or request retry.',
        paid_scope='Previously approved1400 sessions;1000 reused without network, only remaining400 judged',
        original_stopped_status_sha256=sha(OLD/'scoring_001/live_status.json'),frozen_utc=scorer.now()))
    NEW.mkdir();out=NEW/'scoring_001';out.mkdir()
    for arm in p['arms']:
        if(OLD/arm/'completed.json').exists():copy_arm(arm)
    copied={}
    for arm in closed:
        for category in ['sessions','payloads']:
            src=OLD/'scoring_001'/category/arm
            if src.exists():shutil.copytree(src,out/category/arm)
        for category in ['completed_arms','sealed_arms']:
            src=OLD/'scoring_001'/category/(arm+'.json');dst=out/category/src.name;dst.parent.mkdir(exist_ok=True)
            shutil.copy2(src,dst)
        for src in (OLD/'scoring_001/sessions'/arm).glob('*/result.json'):
            dst=out/'sessions'/arm/src.parent.name/src.name
            if sha(src)!=sha(dst):raise ValueError('reused score differs')
            if read(src)['generation_sha256']!=sha(NEW/arm/'generation'/src.parent.name/'result.json'):raise ValueError('canonical closure changed an already judged answer; requires separate audit')
            copied[str(src.relative_to(OLD))]=sha(dst)
    safe_save(out/'reuse_manifest.json',dict(sessions=len(copied),files=copied,rule='Byte-exact completed scores; no call_once on these1000'))
    safe_save(out/'execution_manifest.json',dict(protocol_sha256=sha(scorer.CONFIG),approval_sha256=sha(APPROVAL),continuation_protocol_sha256=sha(PROTOCOL),started_utc=scorer.now()))
    (NEW/'README.md').write_text('# Unicode交付故障后的评分续跑\n\n原answer14b_002全部记录保留。此目录是同一1400会话的规范交付视图，不是新增1400次生成：原始请求不重发；已完成1000份评分逐字节复用，仅剩400份新评分。\n\n所有组执行同一UTF8可交付检查，非法Unicode回答保留original_result.json并标记invalid_unicode_output、失败0分。原图组E20-03的既有本地交付失败同样保留0分。ASCII转义只改变磁盘序列化，不修复字符或模型文本。详见canonical_closures与独立续跑协议。\n',encoding='utf-8')
    print('Prepared canonical view; reused1000 scores without requests',flush=True)

def run():
    p=scorer.verify(APPROVAL);continuation=read(PROTOCOL)
    if sha(Path(__file__))!=continuation['source_sha256']or sha(HERE/'resume_generation.py')!=continuation['safe_writer_sha256']:raise ValueError('continuation source drift')
    out=NEW/'scoring_001'
    # This affects only exclusive on-disk JSON serialization, never prompts or metrics.
    scorer.save=safe_save
    for arm in p['arms']:
        if(out/'completed_arms'/(arm+'.json')).exists():continue
        while not(OLD/arm/'completed.json').exists():
            if(OLD/'controller_stop.json').exists():raise RuntimeError('generation stopped')
            scorer.update(out/'live_status.json',dict(status='waiting_for_completed_generation_arm',active_arm=arm,total_completed=len(list((out/'sessions').glob('*/*/result.json'))),planned=1400,updated_utc=scorer.now(),holdout_started=False));time.sleep(15)
        if not(NEW/arm).exists():copy_arm(arm)
        scorer.verify(APPROVAL)
        sealed=scorer.seal_arm(NEW,out,arm,p);scorer.score_arm(NEW,out,arm,p,sealed)
    bindings={f'{arm}/{qid}':digest for arm in p['arms']for qid,digest in read(out/'completed_arms'/(arm+'.json'))['results_sha256'].items()}
    safe_save(out/'completion.json',dict(sessions=1400,execution_protocol_sha256=sha(scorer.CONFIG),continuation_protocol_sha256=sha(PROTOCOL),results_sha256=bindings,completed_utc=scorer.now()))
    scorer.update(out/'live_status.json',dict(status='scoring_complete',total_completed=1400,planned=1400,updated_utc=scorer.now(),holdout_started=False))
    if not(NEW/'completed.json').exists():safe_save(NEW/'completed.json',dict(status='generation_complete_canonical_view',questions=200,sessions=1400,new_generation_requests=0,source=str(OLD),continuation_protocol_sha256=sha(PROTOCOL)))
    from analyze_e2e import analyze
    analyze(NEW,out,NEW/'analysis_001')

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('action',choices=['prepare','run']);a=ap.parse_args()
    if a.action=='prepare':prepare()
    else:
        try:run()
        except Exception as e:
            scorer.update(NEW/'scoring_001/live_status.json',dict(status='stopped_error',error_type=type(e).__name__,message=str(e),updated_utc=scorer.now()));raise
