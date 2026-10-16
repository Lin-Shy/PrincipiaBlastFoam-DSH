"""Outcome-independent dataset checks; propose review, never edit frozen labels."""
import argparse
from collections import Counter,defaultdict
from pathlib import Path
import re
import sys

PROJECT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(PROJECT/'src'))
from chapter2_v2_retrieval_probe import read,sha,save
from principia_core.retrieval.knowledge_qa import FrozenKnowledgeCorpus


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('dataset','corpus','manifest','output'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();dataset=a.dataset
    corpus=FrozenKnowledgeCorpus(a.corpus,a.manifest)
    questions=read(dataset/'model/questions.json');annotations=read(dataset/'scoring/annotations.json')
    evidence=read(dataset/'scoring/evidence.json');split=read(dataset/'split.json');seal=read(dataset/'dataset-seal.json')
    errors=[]
    for name,digest in seal['files'].items():
        if sha(dataset/name)!=digest:errors.append(dict(kind='frozen_file_hash_mismatch',file=name))
    for eid,span in evidence.items():
        try:
            raw=corpus.read(span['path'],span['line_start'],span['line_end'])
            if raw['sha256']!=span['file_sha256'] or '\n'.join(r['text'] for r in raw['lines'])!=span['excerpt']:
                errors.append(dict(kind='original_evidence_mismatch',evidence_id=eid))
        except (ValueError,OSError,KeyError):errors.append(dict(kind='invalid_original_evidence',evidence_id=eid))
    ids=[q['id'] for q in questions];ann={r['id']:r for r in annotations}
    if len(ids)!=len(set(ids)) or set(ids)!=set(ann):errors.append(dict(kind='question_annotation_identity_mismatch'))
    text_groups=defaultdict(list)
    for q in questions:text_groups[re.sub(r'\s+','',q['question']).casefold()].append(q['id'])
    duplicates=[ids for ids in text_groups.values() if len(ids)>1]
    if duplicates:errors.append(dict(kind='exact_duplicate_questions',ids=duplicates))
    dev,test=set(split['ids']['dev']),set(split['ids']['test'])
    if dev&test or dev|test!=set(ids):errors.append(dict(kind='split_identity_mismatch'))
    devgroups={ann[q]['split_group'] for q in dev};testgroups={ann[q]['split_group'] for q in test}
    if devgroups&testgroups:errors.append(dict(kind='linked_group_leakage',groups=sorted(devgroups&testgroups)))
    for q in annotations:
        known=set(q['required_evidence_ids'])
        if not known or not known<=set(evidence):errors.append(dict(kind='missing_required_evidence',id=q['id']))
        points=q['required_points']
        if not points or any(p['weight']<=0 for p in points):errors.append(dict(kind='invalid_required_points',id=q['id']))
        if any(not set(v.get('evidence_ids',[]))<=known for v in points):errors.append(dict(kind='point_evidence_outside_question',id=q['id']))
    review_items=[dict(id=q['id'],required_points=len(q['required_points']),
        reason='Check each mandatory point is explicitly requested or logically necessary; do not remove points because a model failed.')
        for q in annotations if q['id'] in dev and len(q['required_points'])>=5]
    value=dict(schema='outcome_independent_dataset_audit_v2',formal_result=False,
        dataset_seal_sha256=sha(dataset/'dataset-seal.json'),source_manifest_sha256=sha(a.manifest),
        outcomes_read=False,frozen_files_modified=False,questions=len(ids),verified_original_evidence_spans=len(evidence),
        deterministic_errors=errors,required_point_histogram=dict(Counter(len(q['required_points']) for q in annotations)),
        development_groups=len(devgroups),test_groups=len(testgroups),
        development_content_review_queue=review_items,
        metadata_notes=[dict(field='split.status',value=split.get('status'),
            action='Legacy metadata wording; a future dataset revision should synchronize status with the authoritative seal, never change the frozen file in place.')],
        new_dataset_revision_rules=['Only independently documented source errors, ambiguity, missing premises, or scope mismatch justify edits.',
            'Keep an item-level before/after ledger and apply the same revised questions and rubric to every method.',
            'Do not select or exclude items based on model scores, method advantage, or a desired percentage.',
            'Previously inspected test results are not fresh confirmatory evidence for a tuned method; register independent validation before publication.'])
    save(a.output,value)
    print(dict(questions=len(ids),verified_original_evidence_spans=len(evidence),deterministic_errors=len(errors),development_content_review_queue=len(review_items)))


if __name__=='__main__':main()
