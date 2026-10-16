"""Reuse identical recorded judge requests; never replay old failed requests."""
import hashlib
import json
from pathlib import Path

from chapter2_v2_retrieval_probe import read,save,sha


def request_sha(body):
    return hashlib.sha256(json.dumps(body,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')).hexdigest()


class ExactJudgeReuse:
    def __init__(self,client,source_folder,reference_folder):
        self.client=client;self.deployment=client.deployment
        self.reference_folder=Path(reference_folder)
        self.reused=self.fresh=0;self.new_transport_failed=False
        self.by_request={}
        for path in sorted(Path(source_folder).glob('*.json')):
            record=read(path)
            if record['request_sha256']!=request_sha(record['request']):raise ValueError('Old judge request fingerprint changed')
            if record['endpoint']!=self.deployment.endpoint or record['model']!=self.deployment.model:
                raise ValueError('Cannot reuse a different judge deployment')
            self.by_request.setdefault(record['request_sha256'],(path,record))

    def __call__(self,body,turn):
        match=self.by_request.get(request_sha(body))
        if match is not None:
            path,record=match
            if record['request']!=body:raise ValueError('Judge request identity mismatch')
            if record['status'] in {'prepared','in_flight'}:raise ValueError('Unresolved old request cannot be reissued')
            save(self.reference_folder/(f'{turn:02d}.json'),dict(source_receipt=str(path.absolute()),
                source_receipt_sha256=sha(path),request_sha256=request_sha(body),
                reused=True,new_physical_requests=0,source_status=record['status']))
            self.reused+=1
            return {**record,'exact_request_reused':True}
        self.fresh+=1
        result=self.client(body,turn)
        self.new_transport_failed |= result['status'] in {'http_rejected','transport_error'}
        return result
