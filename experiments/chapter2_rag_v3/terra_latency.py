"""Low-latency Terra candidates; separate records, unchanged scoring content/gates."""
import argparse
import json
import terra_candidate as candidate


def configure():
    candidate.ROOT=candidate.core.DEFAULT_RUN/'evaluation/judges/terra_candidate/latency'
    candidate.PROTOCOL=candidate.core.DEFAULT_RUN/'release/protocol/terra_latency_candidate.json'
    candidate.TRANSPORT_AMENDMENT=candidate.core.DEFAULT_RUN/'release/protocol/terra_latency_transport.json'


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute',action='store_true')
    parser.add_argument('--controls-only',action='store_true')
    args=parser.parse_args();configure()
    print(json.dumps(candidate.run(args.execute,args.controls_only)))
