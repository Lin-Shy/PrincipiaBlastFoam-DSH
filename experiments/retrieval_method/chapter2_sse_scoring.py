"""Separately sealed operational grading wrapper; original v7 remains unchanged."""
import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import sys


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def read(path):return json.loads(path.read_text(encoding='utf-8'))


def install_transport(router, amendment, amendment_sha256):
    """Select only the exact transport registered for this grading phase."""
    if amendment.get('request_admission_policy'):
        from chapter2_spaced_sse_transport import install, POLICY
        if amendment['request_admission_policy'] != POLICY:
            raise ValueError('Unexpected request admission grading policy')
    elif amendment.get('paced_transport_policy'):
        from chapter2_paced_sse_transport import install, POLICY
        if amendment['paced_transport_policy'] != POLICY:
            raise ValueError('Unexpected paced grading transport amendment')
    else:
        from chapter2_sse_record_transport import install
    return install(router, amendment_sha256)


def validate_load_probe(path, amendment_sha256, *, now=None):
    """Admit fresh physical SSE evidence, rather than its summary alone."""
    path=Path(path);probe=read(path)
    age=((now or datetime.now(timezone.utc))-datetime.fromisoformat(probe['created_utc'])).total_seconds()
    rows=probe['results']
    expected={(model,index) for model in ('qwen3-8b','qwen3-14b') for index in range(16)}
    if (probe.get('transport_amendment_sha256')!=amendment_sha256
        or probe.get('formal_result') is not False or probe.get('actual_test_questions_used') is not False
        or probe.get('old_formal_requests_reissued') is not False or probe.get('workers_per_model')!=16
        or not 0<=age<=600 or len(rows)!=32
        or {(row['model'],row['index']) for row in rows}!=expected
        or any(row['status']!='response' for row in rows)):
        raise ValueError('Fresh independent exact-model 16-worker operational probe required')
    for row in rows:
        physical=path.parent/row['model']/str(row['index'])/'requests/00.json'
        record=read(physical)
        if (sha(physical)!=row['receipt_sha256'] or record.get('status')!='response'
            or record.get('transport_revision_sha256')!=amendment_sha256
            or record.get('model')!=row['model'] or record['response'].get('model')!=row['model']):
            raise ValueError('Changed exact-model physical probe receipt')
        raw=(physical.parent/record['raw_sse_file']).resolve()
        if (raw.parent!=physical.parent.resolve() or sha(raw)!=record['raw_response_sha256']
            or record.get('sse_done') is not True):
            raise ValueError('Changed or incomplete physical SSE probe')
        if record['request']!={**record['logical_request'],'stream':True,'stream_options':{'include_usage':True}}:
            raise ValueError('Unexpected operational probe wire transform')
    return probe


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
    validate_load_probe(Path(amendment['required_probe_receipt']),sha(args.transport_amendment))
    sys.path[:0]=[str(frozen/'experiments/retrieval_method'),str(frozen/'src'),str(root/'runtime')]
    from chapter2_full_review import load_reviews
    def argument(name):return Path(remaining[remaining.index('--'+name)+1])
    plan=read(planpath)
    opinions,citations,_=load_reviews(argument('reviews'),plan,sha(planpath),argument('generation'),argument('selection'))
    if len(opinions)!=1536 or len(citations)!=1536:raise ValueError('All 1536 source/citation opinions must precede any grading')
    # Frozen main additionally verifies every one of the 17136 result bindings
    # before it admits its first worker/model request.
    import chapter2_qwen_routing as router
    install_transport(router,amendment,sha(args.transport_amendment))
    if amendment.get('logical_scoring_view_policy'):
        from chapter2_sse_scoring_view import install as install_view, POLICY as VIEW_POLICY
        if amendment['logical_scoring_view_policy']!=VIEW_POLICY:raise ValueError('Unexpected logical scoring view policy')
        install_view(router)
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
