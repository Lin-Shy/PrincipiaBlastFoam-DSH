"""Professional review and one-shot audit lifecycle, called only through scoring.py.

Building the review/locked audit entry does not read sealed answer contents.
"""
import runtime_layout as layout
from contextlib import contextmanager
from html import escape
import hashlib
import json
from pathlib import Path
import random
import statistics

import scoring as core
from judge_contract import VERSION, RULES, schema
from judge_api_adapter import digest

ROOT=core.DEFAULT_RUN/'evaluation/judges'
QUESTIONS=('P06-03','E30-02','E39-01')
DECISIONS={
    'P06-03': '遗漏“不能保证后续全程速度恒定”首先属于K覆盖不足；只有回答实际作出错误条件判断、反向结论或无依据的保证时，才据内容扣A/F，不能因同一遗漏机械重复扣分。保留现有全部人工和AI原始评分。',
    'E30-02': '缺少显式Pa应按必要点的实际专业含义和完整性判断，不自动当作事实错误；writeControl选择写出触发方式，writeInterval指定间隔，只有实质混淆时才影响F。保留现有全部原分。',
    'E39-01': '最近邻可宽泛称为插值，不能只因“插值”一词扣F；“源网格范围”与“已映射单元范围”不能未经核验视为同义，应判断表述是否改变实质适用范围。保留现有全部原分。'
}
STYLE='body{font:16px/1.7 system-ui,"Microsoft YaHei";max-width:1200px;margin:30px auto;padding:0 20px;color:#183047}h1{font-size:26px}section,article{border:1px solid #ccd7e0;border-radius:8px;padding:20px;margin:18px 0}article{background:#f7fafc}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:14px/1.65 Consolas,monospace}td,th{padding:7px 14px;text-align:left;border-bottom:1px solid #ddd}button,select,textarea{font:inherit;padding:8px}textarea{width:95%}.notice{padding:16px;background:#fff3ce}a{color:#17627e}label{display:block;margin:10px 0}'


def protocol():
    """Proposal is bound before audit, never inferred from observed audit scores."""
    path=ROOT/'protocol.json'
    if path.exists():return core.read(path)
    prior=layout.asset('criteria')
    old=core.read(prior)
    value=dict(schema_version=VERSION,status='candidate_pending_professional_confirmation',
        created_utc=core.now(),calibration_accepted_by_owner=True,
        scoring_fingerprints=core.fingerprint(),schema_sha256=digest(schema()),
        statistics=dict(K='necessary-point exact agreement and quadratic weighted kappa, five categories',
            F='five-level agreement/MAE/Bias per answer',A='conditional answers only; N/A excluded by design',
            dual_mean='average the two judges EAS per answer, then compute Human-reference MAE/Bias',
            EAS=['EAS_arith','EAS_geo'],unknown='unknown point estimate and fixed-denominator bounds; no imputation',
            bias='judge minus Human',bootstrap=dict(unit='question cluster',resamples=2000,seed=20261021),
            degenerate_kappa='undefined -> manual review; never replace with 0 or 1',
            no_condition_items='report A as N/A with zero observed items; no applicability reliability claim'),
        audit=dict(answers=12,questions=4,judges=list(core.JUDGES),one_release=True,
            human_blind=True,human_completed_before_ai=True,max_requests=24,automatic_retries=0,
            prompt_optimization_from_audit=False,original_answers_only=True,
            holdout_boundary='Question-ID holdout; historical protocol discloses one shared fact component',
            test160_authorized=False),
        acceptance=dict(status='pending_owner_confirmation',source=prior.relative_to(core.DEFAULT_RUN).as_posix(),
            source_sha256=core.sha(prior),historical_approved=old['approved'],
            K_exact_at_least=old['pass_agreement_at_least'],K_quadratic_kappa_at_least=old['pass_kappa_at_least'],
            each_EAS_mae_at_most=old['pass_mae_at_most'],each_EAS_abs_bias_at_most=old['pass_abs_bias_at_most'],
            scope='each judge separately and dual-mean EAS, both metrics; no metric/judge selection',
            severe_fact_false_passes_at_most=0,substantive_condition_errors_at_most=0,
            error_adjudication='Owner confirms substantive errors; a mere adjacent-score difference is not a proven condition error',
            unknown_for_automatic_pass=0,complete_answers_per_source=12,
            failure='stop automatic freeze/Dev tuning; report differences; do not optimize Prompt on audit'),
        professional_interpretation=DECISIONS,original_scores_modified=False,audit_released=False)
    core.write(path,value)
    return value


def review_packet():
    p=core.load();private={s['sample_id']:s for s in p['private']}
    gold_path=core.DEFAULT_RUN/'data/gold/dev40/annotations.json'
    gold={g['id']:g for g in core.read(gold_path) if g['id'] in QUESTIONS}
    humans=core.collect('human',p['items']);groups=[]
    spans={
        'P06-03':{'tutorials/blastXiFoam/deflagrationToDetonationTransition/0/Su':[(13,23)],
            'tutorials/blastXiFoam/deflagrationToDetonationTransition/constant/combustionProperties':[(17,26)]},
        'E30-02':{'manual/markdown/15_function_objects.md':[(9,24),(131,139)],
            'tutorials/blastFoam/building3D/system/controlDict':[(56,64)]},
        'E39-01':{'manual/markdown/16_utilities.md':[(245,250)]}}
    corpus=core.HUMAN/'versions/phase2_after_coverage_20261023_v1/phase2_evidence/corpus'
    for qid in QUESTIONS:
        items=[i for i in p['items'] if private[i['sample_id']]['question_id']==qid]
        sources=[]
        for source in items[0]['sources']:
            if source['path'] not in spans[qid]:continue
            file=corpus/source['path']
            if core.sha(file)!=source['file_sha256']:raise ValueError('Review source hash mismatch')
            lines=[line for line in source['text'].splitlines() if any(lo<=int(line.split('|',1)[0])<=hi for lo,hi in spans[qid][source['path']])]
            sources.append(dict(path=source['path'],file_sha256=source['file_sha256'],excerpt='\n'.join(lines)))
        groups.append(dict(question_id=qid,question=items[0]['question'],gold=gold[qid],sources=sources,
            suggested_interpretation=DECISIONS[qid],answers=[dict(sample_id=i['sample_id'],method=private[i['sample_id']]['method_id'],
                answer=i['answer'],raw_answer_sha256=private[i['sample_id']]['answer_sha256'],human=humans[i['sample_id']]) for i in items]))
    packet=dict(schema_version=VERSION,calibration_packet_id=p['packet_id'],
        human_source_sha256=core.sha(ROOT/'human_five_level.json'),gold_file_sha256=core.sha(gold_path),groups=groups,
        protocol=protocol())
    packet['review_id']=digest(packet)
    return packet


def verify_dual_mae():
    s=core.read(ROOT/'results/summary.json');byid={}
    for r in s['records']:byid.setdefault(r['sample_id'],{})[r['judge']]=r
    output={}
    for metric in ('EAS_arith','EAS_geo'):
        detail=[]
        for sid,values in byid.items():
            h,g,d=[values[j][metric] for j in ('human',)+core.JUDGES]
            if any(v is None for v in (h,g,d)):raise ValueError('MAE verification requires complete reference pairs')
            average=(g+d)/2
            assert abs(average-s['dual_per_answer'][sid][metric])<1e-10
            detail.append(dict(sample_id=sid,human=h,gpt=g,deepseek=d,dual_mean=average,absolute_error=abs(average-h)))
        actual=statistics.mean(r['absolute_error'] for r in detail)
        wrong=statistics.mean(s['agreement'][j][metric]['mae'] for j in core.JUDGES)
        assert abs(actual-s['dual_mean_vs_human'][metric]['mae'])<1e-10
        output[metric]=dict(pairs=len(detail),correct_per_answer_mean_then_mae=actual,
            incorrect_mean_of_individual_maes=wrong,numerically_equal_in_this_sample=abs(actual-wrong)<1e-10,per_answer=detail)
    # Cancellation example distinguishes the algorithms even if actual errors have the same sign.
    output['counterexample']=dict(human=50,gpt=40,deepseek=60,correct_mae=0,incorrect_mean_mae=10)
    output['calculation']='mean_i(abs((GPT_i + DeepSeek_i)/2 - Human_i))'
    core.write(ROOT/'verification/dual_mae.json',output)
    return output


def build_review():
    if (ROOT/'review_decision.json').exists() and core.read(ROOT/'review_decision.json').get('confirmed'):
        return dict(review=str(ROOT/'review.html'),audit=str(ROOT/'audit/index.html'),
            audit_released=(ROOT/'audit/release.json').exists())
    packet=review_packet();core.write(ROOT/'review_packet.json',packet)
    cards=''
    for g in packet['groups']:
        qid=g['question_id'];gold=g['gold']
        points=''.join('<li>'+escape(p['claim'])+' <small>原权重 '+str(p['weight'])+'（新指标不使用）</small></li>' for p in gold['required_points'])
        answers=''
        for a in g['answers']:
            h=a['human'];scores='，'.join(p['criterion_id']+'='+str(p['score']) for p in h['points'])
            scores+='；F='+str(h['fact_gate'])+'；A='+str(h['applicability_gate'])
            answers+='<article><b>'+escape(a['method'])+' · '+a['sample_id']+'</b><pre>'+escape(a['answer'])+'</pre><p><b>当前人工：'+escape(scores)+'</b></p><details><summary>原始回答哈希</summary><code>'+a['raw_answer_sha256']+'</code></details></article>'
        sources=''.join('<details open><summary>'+escape(s['path'])+'</summary><pre>'+escape(s['excerpt'])+'</pre><small>SHA256 '+s['file_sha256']+'</small></details>' for s in g['sources'])
        goldextra='<p>适用范围：'+escape(gold['applicability'])+'</p><p>可接受表达：'+escape(gold['acceptable_answer_range'])+'</p><p>Gold关键错误：'+escape('；'.join(gold['critical_errors']))+'</p>'
        cards+='<section id="'+qid+'"><h2>'+qid+'</h2><p>'+escape(g['question'])+'</p><h3>Gold必要点（原件不改）</h3><ol>'+points+'</ol>'+goldextra+'<details><summary>完整原Gold记录</summary><pre>'+escape(json.dumps(gold,ensure_ascii=False,indent=2))+'</pre></details><h3>原回答与当前人工分数</h3>'+answers+'<h3>冻结原文（行号保留）</h3>'+sources+'<h3>仅需确认的边界</h3><p class="notice">'+escape(g['suggested_interpretation'])+'</p><label>你的结论 <select data-id="'+qid+'"><option value="">尚未确认</option value="confirm">确认上述边界，原分保留</option value="needs_clarification">需澄清，暂不解封审计</option></select></label><textarea data-note="'+qid+'" rows="2" placeholder="仅有争议时写简短说明"></textarea></section>'
    acceptance='<section id="acceptance"><h2>审计验收门槛：需在看审计结果前确定</h2><p>找到的历史文件仍为未批准的三档草案，并非已生效的五档协议。提议保留原数值：两裁判各自K完全一致率≥90%、五档二次加权Kappa≥0.60；两裁判及逐答平均的两项EAS均MAE≤5分、|Bias|≤3分；12答齐全、Unknown为0；实质严重事实漏判及条件判断错误为0。F/A逐项统计，不把相邻档位差异自动认定为实质错误；退化Kappa或专业争议转人工判断，不自动通过。</p><p>这不是新增结果驱动门槛；原草案数值未改，但五档适用及审批需要你确认。审计失败时停止自动冻结，不用审计结果再调Prompt。</p><label><select data-id="acceptance"><option value="">尚未确认</option><option value="confirm">同意按上述五档审计门槛执行</option><option value="needs_clarification">需要调整门槛（审计仍封存）</option></select></label><textarea data-note="acceptance" rows="2" placeholder="如不同意，请填写门槛；必须在审计结果产生前确定"></textarea></section>'
    payload=json.dumps(dict(schema_version=VERSION,review_id=packet['review_id']),ensure_ascii=False).replace('<','\\u003c')
    script='const binding='+payload+';document.getElementById("export").onclick=()=>{const decisions={};for(const e of document.querySelectorAll("select[data-id]")){decisions[e.dataset.id]={decision:e.value,note:document.querySelector("textarea[data-note=\\""+e.dataset.id+"\\"]").value};}if(Object.values(decisions).some(d=>!d.decision)){document.getElementById("message").textContent="请确认三处边界及审计门槛，或选择需澄清。";return;}const data={...binding,confirmed_utc:new Date().toISOString(),decisions};const a=document.createElement("a"),url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:"application/json"}));a.href=url;a.download="professional_review.json";a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);document.getElementById("message").textContent="已导出复核结论。此操作不修改任何评分；导入确认后才能开放审计。";};'
    html='<!doctype html><meta charset="utf-8"><title>三处专业争议复核</title><style>'+STYLE+'</style><h1>第2章 · 三处专业争议复核</h1><p class="notice">只确认评分边界，不重新评分，不自动改人工、AI或Gold。下方仅9份Dev校准回答；审计回答未读取。必要点遗漏由K体现，F/A需根据实际错误陈述或条件判断评定，不能机械重复扣分。</p><p><a href="#P06-03">P06-03</a> · <a href="#E30-02">E30-02</a> · <a href="#E39-01">E39-01</a> · <a href="#acceptance">审计门槛</a> · <a href="audit/index.html">审计入口</a></p>'+cards+acceptance+'<button id="export">导出专业复核结论</button><p id="message" role="status"></p><script>'+script+'</script>'
    (ROOT/'review.html').write_text(html,encoding='utf-8')
    locked_audit_entry()
    verify_dual_mae()
    return dict(review=str(ROOT/'review.html'),audit=str(ROOT/'audit/index.html'),audit_released=False)


def locked_audit_entry():
    folder=ROOT/'audit';folder.mkdir(exist_ok=True)
    if (folder/'packet.json').exists():return
    (folder/'index.html').write_text('<!doctype html><meta charset="utf-8"><title>独立审计入口</title><style>'+STYLE+'</style><h1>第2章 · 独立人工审计</h1><p class="notice">4题×3方法共12答仍封存。先完成三处专业边界和审计门槛确认，再在本页开放单页面K/F/A联合评分。当前页面不含审计题目、回答、Gold或AI评分。</p><p><a href="../review.html">打开专业争议复核页</a></p><p>确认文件通过 scoring.py import-review --file professional_review.json 导入后，将自动绑定冻结协议并开放此入口。审计人工提交完成前不运行AI评分；审计不用于选择或优化Prompt。</p>',encoding='utf-8')


def definition(p):
    return {k:p[k] for k in ('schema_version','scoring_fingerprints','schema_sha256','statistics',
                             'acceptance','professional_interpretation')}


def frozen_sources():
    return {name:core.sha(core.HERE/name) for name in ('scoring.py','judge_statistics.py','scoring_review.py',
        'human_unified.py','human_unified.js','human_unified_template.html')}


def import_review(path):
    packet=core.read(ROOT/'review_packet.json');data=core.read(path)
    expected=set(QUESTIONS)|{'acceptance'}
    if data.get('schema_version')!=VERSION or data.get('review_id')!=packet['review_id']:
        raise ValueError('Review identity mismatch')
    if digest({k:v for k,v in packet.items() if k!='review_id'})!=packet['review_id']:
        raise ValueError('Review packet changed')
    if set(data.get('decisions',{}))!=expected:raise ValueError('Incomplete review decisions')
    for item in data['decisions'].values():
        if item.get('decision') not in ('confirm','needs_clarification') or not isinstance(item.get('note',''),str):
            raise ValueError('Invalid professional decision')
    if core.sha(ROOT/'human_five_level.json')!=packet['human_source_sha256']:
        raise ValueError('Human reference changed since review')
    file=ROOT/'review_submissions'/(core.sha(path)+'.json');file.parent.mkdir(exist_ok=True)
    if not file.exists():file.write_bytes(Path(path).read_bytes())
    confirmed=all(x['decision']=='confirm' for x in data['decisions'].values())
    if (ROOT/'audit/release.json').exists():
        old=core.read(ROOT/'review_decision.json')
        if old['source_sha256']!=core.sha(path):raise PermissionError('Cannot revise professional protocol after audit release')
        guard_audit();return dict(confirmed=True,audit_released=True)
    core.write(ROOT/'review_decision.json',dict(confirmed=confirmed,source_sha256=core.sha(path),
        source_origin=data.get('source_origin','human_review_page'),decisions=data['decisions'],
        confirmed_utc=data.get('confirmed_utc'),original_scores_modified=False))
    if not confirmed:return dict(confirmed=False,audit_released=False)
    p=protocol()
    if p['scoring_fingerprints']!=core.fingerprint() or p['schema_sha256']!=digest(schema()):
        raise ValueError('Scoring protocol changed before confirmation')
    p['acceptance']['status']='owner_approved_before_audit'
    p['status']='preaudit_frozen';p['confirmed_utc']=core.now()
    p['freeze']=dict(protocol_definition_sha256=digest(definition(p)),source_sha256=frozen_sources(),
        owner_review_sha256=core.sha(path),no_prompt_change=True,no_score_change=True)
    p['freeze']['freeze_id']=digest(p['freeze'])
    core.write(ROOT/'protocol.json',p)
    return prepare_audit()


def guard_audit(require_human=False,require_packet=True):
    file=ROOT/'protocol.json'
    if not file.exists():raise PermissionError('Audit requires a confirmed frozen protocol')
    p=core.read(file)
    if p['status'] not in ('preaudit_frozen','audit_open','audit_complete','final_frozen') or p['acceptance']['status']!='owner_approved_before_audit':
        raise PermissionError('Professional review/acceptance not confirmed')
    if p['scoring_fingerprints']!=core.fingerprint() or p['schema_sha256']!=digest(schema()):
        raise ValueError('Prompt/rules/schema/config changed after pre-audit freeze')
    frozen=p.get('freeze',{})
    if frozen.get('protocol_definition_sha256')!=digest(definition(p)) or not layout.frozen_sources_match(frozen.get('source_sha256',{}),frozen_sources()):
        raise ValueError('Frozen statistics/review implementation changed')
    if frozen.get('freeze_id')!=digest({k:v for k,v in frozen.items() if k!='freeze_id'}):
        raise ValueError('Frozen identity mismatch')
    if require_packet:
        release=ROOT/'audit/release.json'
        if not release.exists():raise PermissionError('Audit not released')
        released=core.read(release)
        if released['packet_sha256']!=core.sha(ROOT/'audit/packet.json') or released['freeze_id']!=frozen['freeze_id']:
            raise ValueError('Released audit packet binding changed')
    if require_human:
        packet=core.read(ROOT/'audit/packet.json')
        with audit_scope():records=core.collect('human',packet['items'])
        if len(records)!=12:raise PermissionError('Complete independent Human audit first; AI not called')
        seal=ROOT/'audit/human_seal.json'
        if seal.exists():
            bound=core.read(seal)
            for name,value in bound['files'].items():
                if core.sha(ROOT/'audit'/name)!=value:raise ValueError('Independent Human audit changed after AI started')
    return p


@contextmanager
def audit_scope():
    previous=core.ROOT;core.ROOT=ROOT/'audit'
    try:yield
    finally:core.ROOT=previous


def prepare_audit():
    p=guard_audit(require_packet=False)
    folder=ROOT/'audit'
    if (folder/'release.json').exists():
        guard_audit();return dict(audit_released=True,answers=12,human=str(folder/'index.html'))
    manifest_path=core.DEFAULT_RUN/'experiments/agentic/reused_inputs/sampling_plan.answers_sealed_v1.json'
    manifest=core.read(manifest_path);manifest_hash=core.sha(manifest_path)
    selected=[s for s in manifest['samples'] if s['batch']=='audit']
    if len(selected)!=12 or len({s['question_id'] for s in selected})!=4:
        raise ValueError('Frozen audit set is not 4 x 3 answers')
    registry=core.Registry()
    if {s['question_id'] for s in selected}!=set(registry.judging['audit_question_ids']):
        raise ValueError('Audit IDs differ from frozen routing')
    split=core.DEFAULT_RUN/'data/dev40'
    questions={q['id']:q['question'] for q in core.read(split/'model/questions.json')}
    annotations={g['id']:g for g in core.read(split/'scoring/annotations.json')}
    evidence=core.read(split/'scoring/evidence.json')
    corpus=core.DEFAULT_RUN/'data/resources/corpus'
    qids=sorted({s['question_id'] for s in selected});rng=random.Random(20261021);rng.shuffle(qids)
    items=[];private=[];ui=[]
    for number,qid in enumerate(qids,1):
        annotation=annotations[qid];conditional=annotation['labels']['condition_discrimination']
        criteria=[dict(criterion_id='K%03d'%(n+1),claim=c['claim']) for n,c in enumerate(annotation['required_points'])]
        sources=[];seen=set()
        for eid in annotation['required_evidence_ids']:
            source=evidence[eid];name=source['path']
            if name in seen:continue
            seen.add(name);source_path=corpus/name
            if core.sha(source_path)!=source['file_sha256']:raise ValueError('Audit original source hash mismatch')
            text='\n'.join('%d|%s'%(n,line) for n,line in enumerate(core.longpath(source_path).read_text(encoding='utf-8-sig').splitlines(),1))
            sources.append(dict(path=name,file_sha256=source['file_sha256'],text=text))
        group=[s for s in selected if s['question_id']==qid];rng.shuffle(group)
        if {s['method_id'] for s in group}!={'graph','bm25','bge_m3'}:raise ValueError('Audit method coverage changed')
        for n,s in enumerate(group):
            if core.sha(s['answer_path'])!=s['answer_sha256']:raise ValueError('Frozen audit answer hash mismatch')
            original=core.read(s['answer_path'])
            sid='S'+hashlib.sha256((manifest_hash+'|'+s['sample_key']).encode()).hexdigest()[:16]
            failed=original['status']!='answered' or not original.get('answer','').strip()
            items.append(dict(schema_version=VERSION,sample_id=sid,question=questions[qid],answer=original['answer'],
                generation_failed=failed,criteria=criteria,conditional=conditional,sources=sources))
            private.append(dict(sample_id=sid,question_id=qid,method_id=s['method_id'],generator_id=s['generator_id'],batch='audit',
                answer_sha256=s['answer_sha256'],conditional=conditional,generation_failed=failed,
                weights={c['criterion_id']:annotation['required_points'][j]['weight'] for j,c in enumerate(criteria)}))
            ui.append(dict(sample_id=sid,group_id='A%02d'%number,label='回答'+('甲','乙','丙')[n],legacy=None))
    packet=dict(schema_version=VERSION,batch='audit',packet_id=digest(dict(items=items,rules=RULES)),
        fingerprints=core.fingerprint(),items=items,private=private,ui=ui,audit_included=True,test160_included=False,
        human_blind=True,sampling_manifest_sha256=manifest_hash,freeze_id=p['freeze']['freeze_id'])
    core.write(folder/'packet.json',packet)
    # The source files stay sealed in place; this separate export is authorized only now.
    core.write(folder/'release.json',dict(released_utc=core.now(),questions=4,answers=12,
        packet_sha256=core.sha(folder/'packet.json'),freeze_id=p['freeze']['freeze_id'],
        review_source_sha256=p['freeze']['owner_review_sha256'],original_answers_modified=False,
        prompt_optimization_allowed=False,human_blind=True,test160_started=False))
    p.update(status='audit_open',audit_released=True);core.write(ROOT/'protocol.json',p)
    from human_unified import build_page
    with audit_scope():
        build_page(packet)
        # Do not create an AI-results dashboard beside the Human audit until Human completes.
    review=ROOT/'review.html'
    text=review.read_text(encoding='utf-8')
    marker='<h1>第2章 · 三处专业争议复核</h1>'
    text=text.replace(marker,marker+'<p class="notice">三处边界及审计门槛已由研究者确认，全部原分保留。独立人工审计已开放，使用本页顶部审计入口进入。</p>')
    text=text.replace('<option value="confirm">','<option value="confirm" selected>')
    text=text.replace('<button id="export">导出专业复核结论</button>','<button id="export" disabled>已确认，原分保留</button>')
    review.write_text(text,encoding='utf-8')
    core.write(folder/'status.json',dict(status='awaiting_independent_human',human_answers=0,expected_answers=12,ai_requests=0))
    return dict(audit_released=True,answers=12,human=str(folder/'index.html'),ai_requests=0)


def import_audit_human(path):
    guard_audit()
    if (ROOT/'audit/requests/ledger.jsonl').exists():
        original=core.read(ROOT/'audit/human/import_validation.json')
        if core.sha(path)!=original['source_sha256']:
            raise PermissionError('Human audit reference is sealed once AI requests start')
    with audit_scope():
        core.import_human(path)
        packet=core.load();records=core.collect('human',packet['items'])
    core.write(ROOT/'audit/status.json',dict(status='human_complete_ready_for_ai' if len(records)==12 else 'awaiting_independent_human',
        human_answers=len(records),expected_answers=12,ai_requests=len(core.rows(ROOT/'audit/requests/ledger.jsonl'))))
    return dict(confirmed_human_answers=len(records),expected_answers=12)


def audit_score(execute=False):
    guard_audit(require_human=execute)
    if execute and not (ROOT/'audit/human_seal.json').exists():
        files={name:core.sha(ROOT/'audit'/name) for name in ('human/scores.jsonl','human/draft.json','human/import_validation.json')}
        core.write(ROOT/'audit/human_seal.json',dict(sealed_utc=core.now(),files=files,independent_before_ai=True))
    with audit_scope():core.score(execute)
    result=audit_report() if execute else dict(requests_sent=0)
    if execute and result['accepted']:finalize()
    return result


def evaluate_audit(summary, criteria, labels, items):
    """Apply owner-approved gates; no judge or metric can be silently substituted."""
    missing=[];failed=[];manual=[]
    for judge in ('human',)+core.JUDGES:
        if len(labels[judge])!=12:missing.append(judge)
    if missing:return dict(decision='pending_human_or_judges',missing_sources=missing,accepted=False)
    if any(r['unknown_items'] or r['missing_items'] for r in summary['records']):manual.append('unknown_or_missing_labels')
    for judge in core.JUDGES:
        a=summary['agreement'][judge]['K']
        if a['exact'] is None or a['quadratic_kappa'] is None:manual.append(judge+':undefined_K_statistic')
        else:
            if a['exact']<criteria['K_exact_at_least']:failed.append(judge+':K_exact')
            if a['quadratic_kappa']<criteria['K_quadratic_kappa_at_least']:failed.append(judge+':K_kappa')
    for judge,agreement in dict(summary['agreement'],dual_mean=summary['dual_mean_vs_human']).items():
        for metric in ('EAS_arith','EAS_geo'):
            a=agreement[metric]
            if a['identified_pairs']!=12:manual.append(judge+':'+metric+':incomplete')
            else:
                if a['mae']>criteria['each_EAS_mae_at_most']:failed.append(judge+':'+metric+':MAE')
                if abs(a['bias_right_minus_left'])>criteria['each_EAS_abs_bias_at_most']:failed.append(judge+':'+metric+':Bias')
    red_flags=[]
    for item in items:
        sid=item['sample_id'];human=labels['human'][sid]
        for judge in core.JUDGES:
            record=labels[judge][sid];hf=human['fact_gate'];jf=record['fact_gate']
            if type(hf) in (int,float) and type(jf) in (int,float) and hf<=.25 and jf>=.75:
                red_flags.append(dict(sample_id=sid,judge=judge,kind='potential_severe_fact_false_pass'))
            if item['conditional']:
                ha=human['applicability_gate'];ja=record['applicability_gate']
                if type(ha) in (int,float) and type(ja) in (int,float) and abs(ha-ja)>=.5:
                    red_flags.append(dict(sample_id=sid,judge=judge,kind='potential_substantive_condition_error'))
    if red_flags:manual.append('professional_error_adjudication_required')
    decision='fail' if failed else 'manual_review' if manual else 'pass_observed_audit_only'
    return dict(decision=decision,accepted=decision=='pass_observed_audit_only',failed_gates=failed,
        manual_reasons=manual,professional_red_flags=red_flags,
        red_flag_definition='Human F<=0.25 vs AI F>=0.75; or conditional |AI A-Human A|>=0.5; flags require professional adjudication',
        adjacent_omission_differences_not_automatically_condition_errors=True,population_accuracy_proven=False)


def audit_report():
    p=guard_audit()
    with audit_scope():
        summary=core.report();packet=core.load();labels={j:core.collect(j,packet['items']) for j in ('human',)+core.JUDGES}
    result=evaluate_audit(summary,p['acceptance'],labels,packet['items'])
    result.update(freeze_id=p['freeze']['freeze_id'],created_utc=core.now(),prompt_optimization_allowed=False,test160_started=False)
    path=ROOT/'audit/results/acceptance.json'
    if path.exists():
        existing=core.read(path)
        if {k:v for k,v in existing.items() if k!='created_utc'}=={k:v for k,v in result.items() if k!='created_utc'}:
            return existing
    core.write(path,result)
    return result


def finalize():
    p=guard_audit();result=audit_report()
    if not result['accepted']:raise PermissionError('Independent audit has not met the approved acceptance conditions')
    p.update(status='final_frozen',reliability_accepted=True,final_frozen_utc=core.now(),
        audit_acceptance_sha256=core.sha(ROOT/'audit/results/acceptance.json'),dev40_tuning_ready=True,
        test160_started=False,test160_authorized=False)
    core.write(ROOT/'protocol.json',p)
    # This marks the statistical gate only. Generation must still respect the exact
    # frozen production questions and per-model/method parameter identity.
    core.report()
    with audit_scope():core.report()
    return dict(status='final_frozen',dev40_tuning_ready=True,test160_authorized=False)
