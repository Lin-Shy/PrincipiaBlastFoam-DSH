"""Separately sealed operational grading wrapper; original v7 remains unchanged."""
import argparse
import hashlib
import json
from pathlib import Path
import sys


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def read(path):return json.loads(path.read_text(encoding='utf-8'))


def main():
    parser=argparse.ArgumentParser(add_help=False)
    parser.add_argument('--transport-amendment',type=Path,required=True)
    args,remaining=parser.parse_known_args()
    amendment=read(args.transport_amendment);root=args.transport_amendment.parent
    if amendment['schema'] != 'explicit_sse_scoring_amendment_v1':raise ValueError('Wrong grading amendment')
    for relative,expected in amendment['adapter_source_sha256'].items():
        if sha(root/relative)!=expected:raise ValueError('Changed registered grading wrapper source')
    planpath=Path(remaining[remaining.index('--plan')+1]);frozen=planpath.parent/'runtime'
    if sha(planpath)!=amendment['plan_sha256'] or sha(frozen/'experiments/retrieval_method/chapter2_full_scoring.py')!=amendment['frozen_scoring_sha256']:
        raise ValueError('Changed frozen plan or v7 grading source')
    probe=read(Path(amendment['required_probe_receipt']))
    if (probe['transport_amendment_sha256']!=sha(args.transport_amendment)
        or probe['actual_test_questions_used'] is not False or probe['old_formal_requests_reissued'] is not False
        or len(probe['results'])!=32 or any(r['status']!='response' for r in probe['results'])
        or any(sum(r['model']==m for r in probe['results'])!=16 for m in ['qwen3-8b','qwen3-14b'])):
        raise ValueError('Independent exact-model operational probe required')
    sys.path[:0]=[str(frozen/'experiments/retrieval_method'),str(frozen/'src'),str(root/'runtime')]
    from chapter2_full_review import load_reviews
    def argument(name):return Path(remaining[remaining.index('--'+name)+1])
    plan=read(planpath)
    opinions,citations,_=load_reviews(argument('reviews'),plan,sha(planpath),argument('generation'),argument('selection'))
    if len(opinions)!=1536 or len(citations)!=1536:raise ValueError('All 1536 source/citation opinions must precede any grading')
    # Frozen main additionally verifies every one of the 17136 result bindings
    # before it admits its first worker/model request.
    import chapter2_qwen_routing as router
    from chapter2_sse_record_transport import install
    install(router,sha(args.transport_amendment))
    import chapter2_score_knowledge_formal as scoring
    from chapter2_surrogate_scoring import wrap,POLICY
    if amendment['unicode_input_policy']!=POLICY:raise ValueError('Unexpected input-admission policy')
    scoring.score_answer=wrap(scoring.score_answer)
    import chapter2_full_scoring as generation
    from chapter2_lossless_json import save,POLICY as SAVE_POLICY
    if amendment['persistence_policy']!=SAVE_POLICY:raise ValueError('Unexpected persistence policy')
    generation.save=save
    sys.argv=[str(frozen/'experiments/retrieval_method/chapter2_full_scoring.py')]+remaining
    generation.main()


if __name__=='__main__':main()
