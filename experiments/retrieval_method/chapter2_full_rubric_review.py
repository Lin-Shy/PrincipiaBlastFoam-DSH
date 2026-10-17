"""Source-only test-rubric audit before new formal answers; suggestions only."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path

from chapter2_review_rubric_necessity import REVIEW,VERIFY,body,parse_proposal,parse_verification,PROJECT
from chapter2_v2_retrieval_probe import read,save,sha
from chapter2_offline_dataset_calls import MODEL,ENDPOINT,call,key_from_config
from chapter2_full_protocol import verify_dataset
from principia_core.retrieval.knowledge_qa import FrozenKnowledgeCorpus


def prepare_inputs(dataset,resources):
    questions={q['id']:q['question'] for q in read(dataset/'model/questions.json')}
    annotations={r['id']:r for r in read(dataset/'scoring/annotations.json')}
    evidence=read(dataset/'scoring/evidence.json');ids=read(dataset/'split.json')['ids']['test']
    if len(ids)!=200 or len(set(ids))!=200:raise ValueError('Entire original 200-question test cohort required')
    corpus=FrozenKnowledgeCorpus(resources['corpus'],resources['corpus_manifest']);payloads={}
    for qid in ids:
        annotation=annotations[qid];sources={}
        for eid in annotation['required_evidence_ids']:
            e=evidence[eid];raw=corpus.read(e['path'],e['line_start'],e['line_end'])
            if raw['sha256']!=e['file_sha256'] or '\n'.join(r['text'] for r in raw['lines'])!=e['excerpt']:
                raise ValueError('Original rubric source changed')
            sources[eid]=raw
        # No candidate answer, model/method label, previous score or outcome.
        payloads[qid]=dict(id=qid,question=questions[qid],
            annotation=dict(required_points=annotation['required_points'],required_evidence_ids=annotation['required_evidence_ids']),sources=sources)
    return payloads


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('dataset','resources','output','dsh-home'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--workers',type=int,default=4);args=parser.parse_args()
    if args.output.exists():raise FileExistsError('New immutable source-only rubric audit required')
    if not 1<=args.workers<=4:raise ValueError('Offline audit uses at most four workers')
    seal_sha=sha(args.dataset/'dataset-seal.json');verify_dataset(args.dataset,seal_sha)
    resources=read(args.resources);inputs=prepare_inputs(args.dataset,resources)
    key=key_from_config(args.dsh_home)
    sources=[Path(__file__),Path(PROJECT/'experiments/retrieval_method/chapter2_review_rubric_necessity.py'),
        Path(PROJECT/'experiments/retrieval_method/chapter2_offline_dataset_calls.py')]
    save(args.output/'protocol.json',dict(schema='complete_test_source_only_rubric_audit_v4',formal_result=False,
        model=MODEL,endpoint=ENDPOINT,question_ids=list(inputs),question_count=200,dataset_seal_sha256=seal_sha,
        candidate_answers_or_scores_provided=False,source_selection='Original necessary source spans; insufficient scope is flagged, never invented.',
        historical_test_exposure=True,reference_before_new_formal_answers=True,review_prompt=REVIEW,verify_prompt=VERIFY,
        workers=args.workers,max_transport_attempts=3,content_retries=0,human_truth=False,
        policy='Suggestions only. Preserve original gold and original-v7 primary. Host source verification and a separate registered version are required for changes.',
        implementation_sha256={str(p.relative_to(PROJECT)):sha(p) for p in sources}))
    save(args.output/'inputs.json',inputs)
    for path in sources:
        target=args.output/'runtime'/path.name;target.parent.mkdir(exist_ok=True);target.write_bytes(path.read_bytes())
    def work(qid):
        payload=inputs[qid];folder=args.output/'sessions'/qid
        proposal=call('necessity',body(REVIEW,payload),folder,key,parse_proposal)
        if proposal['status']!='response':return dict(id=qid,status=proposal['status'],stage='necessity')
        verified=call('verify',body(VERIFY,{**payload,'proposal':proposal['parsed']}),folder,key,parse_verification)
        if verified['status']!='response':return dict(id=qid,status=verified['status'],stage='verify')
        save(folder/'review.json',dict(id=qid,status='reviewed_suggestions_only',proposal=proposal['parsed'],verification=verified['parsed'],
            proposal_response_sha256=sha(folder/'responses/necessity.json'),verification_response_sha256=sha(folder/'responses/verify.json')))
        return dict(id=qid,status='reviewed_suggestions_only')
    statuses=Counter()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures={pool.submit(work,qid):qid for qid in inputs}
        for future in as_completed(futures):
            result=future.result();statuses[result['status']]+=1
            print(dict(completed=sum(statuses.values()),planned=200,**result),flush=True)
    if sha(args.dataset/'dataset-seal.json')!=seal_sha:raise ValueError('Original dataset changed during audit')
    verify_dataset(args.dataset,seal_sha)
    save(args.output/'completion.json',dict(planned=200,terminal=sum(statuses.values()),statuses=dict(statuses),
        all_reviewed=statuses['reviewed_suggestions_only']==200,frozen_dataset_modified=False,suggestions_are_not_accepted_changes=True))


if __name__=='__main__':main()
