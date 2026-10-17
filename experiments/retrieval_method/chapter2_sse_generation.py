"""Run the frozen generation under a separately sealed, disclosed SSE amendment."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p):return json.loads(p.read_text(encoding='utf-8'))

def main():
    parser=argparse.ArgumentParser(add_help=False)
    parser.add_argument('--transport-amendment',type=Path,required=True)
    args,remaining=parser.parse_known_args()
    amendment=read(args.transport_amendment);root=args.transport_amendment.parent
    if amendment['schema']!='explicit_sse_generation_amendment_v1':raise ValueError('Wrong amendment schema')
    for relative,expected in amendment['adapter_source_sha256'].items():
        if sha(root/relative)!=expected:raise ValueError('Changed registered SSE source')
    probe=read(Path(amendment['required_probe_receipt']))
    if (probe['transport_amendment_sha256']!=sha(args.transport_amendment)
        or probe['formal_result'] is not False or probe['actual_test_questions_used'] is not False
        or probe['old_formal_requests_reissued'] is not False or len(probe['results'])!=32
        or any(r['status']!='response' for r in probe['results'])
        or any(sum(r['model']==m for r in probe['results'])!=16 for m in ['qwen3-8b','qwen3-14b'])):
        raise ValueError('Successful independent 16-worker probe required for both exact models')
    plan=Path(remaining[remaining.index('--plan')+1]);frozen=plan.parent/'runtime'
    if sha(plan)!=amendment['plan_sha256'] or sha(frozen/'experiments/retrieval_method/chapter2_full_generation.py')!=amendment['frozen_generation_sha256']:
        raise ValueError('Changed frozen plan or generation source')
    sys.path[:0]=[str(frozen/'experiments/retrieval_method'),str(frozen/'src'),str(root/'runtime')]
    import chapter2_qwen_routing as router
    if amendment.get('paced_transport_policy'):
        from chapter2_paced_sse_transport import install, POLICY
        if amendment['paced_transport_policy'] != POLICY:
            raise ValueError('Unexpected paced transport amendment')
    else:
        from chapter2_sse_record_transport import install
    install(router,sha(args.transport_amendment))
    import chapter2_full_generation as generation
    if amendment.get('persistence_policy'):
        from chapter2_lossless_json import save, POLICY
        if amendment['persistence_policy'] != POLICY:
            raise ValueError('Unexpected persistence amendment')
        generation.save = save
    if amendment.get('admission_policy'):
        from chapter2_generation_circuit import wrap_scheduler, POLICY
        if amendment['admission_policy'] != POLICY:
            raise ValueError('Unexpected admission amendment')
        receipt=Path(remaining[remaining.index('--receipt')+1])
        generation.run_per_model=wrap_scheduler(generation.run_per_model,
            receipt/'admission-events.jsonl',sha(args.transport_amendment))
    frozen_main = generation.main
    sys.argv=[str(frozen/'experiments/retrieval_method/chapter2_full_generation.py')]+remaining
    frozen_main()

if __name__=='__main__':main()
