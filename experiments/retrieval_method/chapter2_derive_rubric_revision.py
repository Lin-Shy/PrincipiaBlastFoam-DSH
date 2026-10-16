"""Derive an explicitly reviewed development rubric, preserving every question."""
import argparse
from copy import deepcopy
from datetime import datetime,timezone
import json
from pathlib import Path
import shutil

from chapter2_v2_retrieval_probe import read,save,sha


def revise(annotations,decisions,dev_ids):
    rows=deepcopy(annotations);by_id={r['id']:r for r in rows};ledger=[];seen=set()
    for decision in decisions:
        qid=decision['question_id'];pid=decision['point_id']
        if qid not in dev_ids or (qid,pid) in seen:raise ValueError('Revision must uniquely target existing development points')
        seen.add((qid,pid));row=by_id[qid]
        points={p['id']:p for p in row['required_points']}
        if pid not in points or points[pid]['claim']!=decision['old_claim']:raise ValueError('Reviewed original claim differs')
        if not decision['reason'].strip() or not decision['question_basis'].strip() or not decision['source_basis'].strip():
            raise ValueError('Each change needs question/source reasons, not outcome targets')
        new=decision['new_claim']
        if new is not None and (not isinstance(new,str) or not new.strip()):raise ValueError('Invalid revised mandatory claim')
        if new is None:
            row['required_points']=[p for p in row['required_points'] if p['id']!=pid]
            for ids in row.get('source_contributions',{}).values():
                if pid in ids:ids.remove(pid)
        else:points[pid]['claim']=new
        for error in decision.get('remove_critical_errors',[]):
            if error not in row['critical_errors']:raise ValueError('Reviewed critical error differs')
            row['critical_errors'].remove(error)
        if not row['required_points']:raise ValueError('Cannot remove every mandatory point')
        ledger.append(decision)
    return rows,ledger


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('dataset','decisions','output'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args()
    if a.output.exists():raise FileExistsError('New dataset revision required')
    original_seal=read(a.dataset/'dataset-seal.json')
    for relative,digest in original_seal['files'].items():
        if sha(a.dataset/relative)!=digest:raise ValueError('Original frozen dataset changed')
    decisions=read(a.decisions)
    if decisions['human_truth'] is not False or decisions['reviewer']!='codex_source_review':
        raise ValueError('Explicit AI/source review identity required')
    if decisions['original_dataset_seal_sha256']!=sha(a.dataset/'dataset-seal.json'):
        raise ValueError('Decision ledger binds another dataset')
    revised,ledger=revise(read(a.dataset/'scoring/annotations.json'),decisions['approved_changes'],set(read(a.dataset/'split.json')['ids']['dev']))
    for relative in original_seal['files']:
        if relative in {'scoring/annotations.json','README.md','assembly.json','validation.json'}:continue
        target=a.output/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(a.dataset/relative,target)
    save(a.output/'scoring/annotations.json',revised)
    readme='''# Development rubric necessity revision

All 277 original questions, splits, sources, retained point weights and test annotations are preserved. Only individually reviewed development requirements and one corresponding unasked-background omission rule change. No failed item is removed. This is posthoc development sensitivity, not a fresh formal validation or human Gold. See revision.json for every reason. The historical version remains intact. The evidence pool is retained for comparable retrieval diagnostics.
'''
    (a.output/'README.md').write_text(readme,encoding='utf-8')
    revision=dict(schema='development_rubric_necessity_revision_v1',created_utc=datetime.now(timezone.utc).isoformat(),
        status='posthoc_development_sensitivity_not_formal',human_truth=False,
        parent_dataset_seal_sha256=sha(a.dataset/'dataset-seal.json'),decisions_sha256=sha(a.decisions),
        changed_questions=len({r['question_id'] for r in ledger}),changed_points=len(ledger),changes=ledger,
        questions_changed=0,questions_removed=0,split_changed=False,old_scores_overwritten=False,
        limits='Question-aligned mandatory-point revision. Results are separate from original scores and cannot establish fresh confirmatory superiority.')
    save(a.output/'revision.json',revision)
    original=read(a.dataset/'scoring/annotations.json')
    dev=set(read(a.dataset/'split.json')['ids']['dev'])
    unchanged_tests=all(before==after for before,after in zip(original,revised) if before['id'] not in dev)
    if not unchanged_tests or len(original)!=len(revised):raise ValueError('Test annotation or denominator changed')
    save(a.output/'assembly.json',dict(schema='development_rubric_derivation_v1',
        parent_assembly_sha256=sha(a.dataset/'assembly.json'),revision_sha256=sha(a.output/'revision.json'),
        notes='Parent assembly is provenance, not fresh generation or semantic validation.'))
    valid_ids=all(set(ids)<=set(p['id'] for p in r['required_points']) for r in revised for ids in r.get('source_contributions',{}).values())
    if not valid_ids:raise ValueError('Dangling source contribution')
    save(a.output/'validation.json',dict(schema='development_rubric_derivation_validation_v1',
        annotations_sha256=sha(a.output/'scoring/annotations.json'),all_questions_retained=len(original)==len(revised),
        public_questions_unchanged=sha(a.output/'model/questions.json')==sha(a.dataset/'model/questions.json'),
        split_unchanged=sha(a.output/'split.json')==sha(a.dataset/'split.json'),test_annotations_unchanged=unchanged_tests,
        contribution_ids_valid=valid_ids,independent_human_semantic_validation=False,
        parent_validation_sha256=sha(a.dataset/'validation.json')))
    files={relative:sha(a.output/relative) for relative in original_seal['files']}
    files['revision.json']=sha(a.output/'revision.json')
    save(a.output/'dataset-seal.json',dict(schema='development_knowledge_rubric_revision_seal_v1',status='development_sensitivity_only',
        version=a.output.name,parent_sha256=sha(a.dataset/'dataset-seal.json'),files=files,counts=original_seal['counts'],
        independent_production_corpus_manifest_sha256=original_seal['independent_production_corpus_manifest_sha256'],
        experiment_ready=False,human_truth=False))
    print(json.dumps(dict(changed_questions=revision['changed_questions'],changed_points=len(ledger),question_count=len(revised),original_questions_unchanged=True)),flush=True)


if __name__=='__main__':main()
