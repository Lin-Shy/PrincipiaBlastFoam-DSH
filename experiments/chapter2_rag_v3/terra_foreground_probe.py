"""Native nonstream JSON / no-reasoning capability probe, separate from SSE trials."""
import argparse
from copy import deepcopy
import json
import terra_background_probe as probe


def request(item):
    profile,req,count=probe.native.request(item,'none')
    profile=deepcopy(profile);req=deepcopy(req);profile['stream']=False
    req['body'].update(stream=False,store=False,text={'format':{'type':'json_object'}})
    req.update(profile_sha256=probe.digest(profile),request_sha256=probe.digest(req['body']))
    assert count+profile['output_token_cap']<=32768
    return profile,req,count


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--execute',action='store_true');args=parser.parse_args()
    probe.ROOT=probe.c.core.DEFAULT_RUN/'evaluation/judges/terra_candidate/foreground'
    probe.PROTOCOL=probe.c.core.DEFAULT_RUN/'release/protocol/terra_foreground_probe.json'
    probe.request=request
    print(json.dumps(probe.probe(args.execute)))
