"""Run frozen generation with an independently sealed byte-preserving TLS adapter."""
import argparse
import hashlib
import json
from pathlib import Path
import sys


def read(path):return json.loads(path.read_text(encoding='utf-8'))
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--transport-amendment', type=Path, required=True)
    args, remaining = parser.parse_known_args()
    amendment = read(args.transport_amendment)
    if amendment['schema'] != 'byte_preserving_tls_generation_amendment_v1':raise ValueError('Wrong transport amendment')
    root = args.transport_amendment.parent
    for relative, expected in amendment['adapter_source_sha256'].items():
        if sha(root / relative) != expected:raise ValueError('Changed registered TLS adapter')
    probe = read(Path(amendment['required_probe_receipt']))
    if (probe['transport_amendment_sha256'] != sha(args.transport_amendment)
            or probe['formal_result'] is not False or probe['old_formal_requests_reissued'] is not False
            or len(probe['results']) != 32
            or any(r['status'] != 'response' for r in probe['results'])
            or any(sum(r['model'] == m for r in probe['results']) != 16 for m in ('qwen3-8b','qwen3-14b'))):
        raise ValueError('Both exact models need a completed 16-worker operational probe')
    plan = Path(remaining[remaining.index('--plan')+1])
    if sha(plan) != amendment['plan_sha256']:raise ValueError('Transport amendment binds another plan')
    frozen = plan.parent/'runtime'
    if sha(frozen/'experiments/retrieval_method/chapter2_full_generation.py') != amendment['frozen_generation_sha256']:
        raise ValueError('Frozen generation changed')
    # This adapter is a disclosed supplement to the frozen source closure, not
    # an edited graph, prompt, budget, model, result or original protocol.
    sys.path[:0] = [str(frozen/'experiments/retrieval_method'), str(frozen/'src'), str(root/'runtime')]
    import chapter2_qwen_routing as router
    from chapter2_tls_record_transport import install
    install(router, sha(args.transport_amendment))
    from chapter2_full_generation import main as frozen_main
    sys.argv = [str(frozen/'experiments/retrieval_method/chapter2_full_generation.py')] + remaining
    frozen_main()


if __name__ == '__main__':main()
