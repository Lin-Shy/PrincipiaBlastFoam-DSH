"""仅验证待审格式及冻结前置条件；不创建留出题、不运行留出检索。"""
import argparse
from collections import Counter
from common import *

def template():
    save(ARCHIVE/'holdout/holdout_freeze_manifest.template.json',dict(status='not_frozen',
        target_questions=60,types_each=15,model_input='id and question only',
        scoring_side='required points/weights/applicability/evidence separated',
        required_human_signoffs=['all60 questions and labels confirmed','fact/case/evidence-combination overlap audit completed',
                                 'remaining overlap quantified','method/hyperparameter/prompt/judge/statistics decisions completed on exposed200'],
        required_bindings=dict(public_questions_sha256=None,scoring_annotations_sha256=None,evidence_sha256=None,
            human_confirmation_sha256=None,overlap_audit_sha256=None,method_code_sha256=None,
            generation_protocol_sha256=None,judge_protocol_sha256=None,model_revision=None,source_map_sha256=None),
        confirmatory_arms=['graph','bm25','bge_m3','bm25_bge_m3','bm25_parent'],optional_ablations=['no_traversal','anchor_only'],
        planned_sessions_min=300,planned_sessions_with_ablations=420,
        execution_approval='separate explicit user approval required before any holdout retrieval or QA',
        freeze_rule='No pending fields. Independent human review and fact overlap audit required. Any post-test bug fix is logged and cannot reset first-exposure status.',
        results='not_started'))
    print('holdout template only; not frozen, no questions or scores created')

def validate(public,annotations,human,overlap,output):
    qs=read(public);labels=read(annotations);h=read(human);audit=read(overlap)
    if len(qs)!=60 or any(set(q)!={'id','question'} for q in qs):raise ValueError('60 public-only questions required')
    if len({q['id'] for q in qs})!=60 or {q['id'] for q in qs}!={a['id'] for a in labels}:raise ValueError('holdout identities mismatch')
    if {q['id'] for q in qs}&{q['id'] for q in public_questions()}:raise ValueError('holdout public ids overlap')
    counts=Counter((a['labels']['evidence_integration'],a['labels']['condition_discrimination']) for a in labels)
    if len(counts)!=4 or set(counts.values())!={15}:raise ValueError('holdout types must be15 each')
    for a in labels:
        if not a.get('required_points') or any(p.get('weight',0)<=0 for p in a['required_points']):raise ValueError('positive weights required')
        if not a.get('required_evidence_ids'):raise ValueError('holdout registered evidence required')
    if h.get('status')!='human_confirmed' or set(h.get('question_ids',[]))!={q['id'] for q in qs}:raise ValueError('real human signoff required')
    if audit.get('status')!='human_confirmed' or 'fact_overlap_count' not in audit or 'evidence_combination_overlap_count' not in audit:raise ValueError('quantified human fact isolation audit required')
    save(ARCHIVE/'holdout'/output,dict(status='format_and_signoff_validated_only_not_experiment_frozen',
        checks='passed',bindings={n:sha(p) for n,p in [('public',public),('annotations',annotations),('human',human),('overlap',overlap)]},
        new_holdout_queries=0))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['template','validate'])
    for name in ['public','annotations','human','overlap']:p.add_argument('--'+name,type=Path)
    p.add_argument('--output');a=p.parse_args()
    template() if a.action=='template' else validate(a.public,a.annotations,a.human,a.overlap,a.output)
