"""Close E20-03 from recorded API replies and recorded retrieval, without network.

Re-ranking emits elapsed timings, so equality of a fresh trace is not a valid
replay test. Replay the recorded ranges, then the original tool implementation
reads and validates original source text. Every resulting API body must equal
the original recorded body. No provider call is permitted by this process.
"""
import sys
from common import *

def main():
    import retrieval
    import resume_generation
    original=retrieval.GraphEngine
    folder=ARCHIVE/'e2e_runs/answer14b_002/graph/generation/E20-03'
    traces=[read(path)for path in sorted((folder/'retrieval_traces').glob('*.json'))]
    class RecordedRanges(original):
        calls=0
        def query(self,query):
            saved=traces[self.calls];self.calls+=1
            if query!=saved['query']:raise ValueError('replay query differs')
            return saved['trace']['selected_slots'],saved['trace']
    retrieval.GraphEngine=RecordedRanges
    def no_network(event,args):
        if event in {'socket.connect','socket.connect_ex','socket.getaddrinfo'}:raise PermissionError('offline closure cannot call API')
    sys.addaudithook(no_network)
    resume_generation.worker('graph',True)
    recovered=read(folder/'recovered_result.json')
    save(ARCHIVE/'e2e_runs/answer14b_002/local_closure.json',dict(question='E20-03',arm='graph',
        original_empty_result_sha256=sha(ARCHIVE/'e2e_runs/answer14b_001/graph/generation/E20-03/result.json'),
        recovered_result_sha256=sha(folder/'recovered_result.json'),canonical_result_sha256=sha(folder/'result.json'),
        recovered_status=recovered['status'],canonical_status='local_result_serialization_failure',score_policy='generation_failure0',
        recorded_requests=2,new_network_calls=0,unicode_surrogate_count=sum(0xd800<=ord(c)<=0xdfff for c in (recovered.get('answer')or'')),
        replay='Original recorded retrieval slots plus freshly hash-validated source text; resulting API request bodies byte-semantically identical',
        script_sha256=sha(Path(__file__))))
    print('Closed E20-03 offline; original empty file retained; no requests resent; failure0')

if __name__=='__main__':main()
