"""全200题的独立Dense运行与融合右路重复性、实际通道/输入核验。"""
from common import *

def main(run_id):
    root=ARCHIVE/'runs'/run_id
    completed={m:read(root/m/'completed.json') for m in ['bge_m3','bm25_bge_m3']}
    for m,c in completed.items():
        assert not c['scoring_reads'] and not c['graph_reads']
        assert not any(Path(p).name in ['sparse_linear.pt','colbert_linear.pt'] for p in c['opened_files'])
    for q in public_questions():
        left=read(root/'bge_m3/traces'/(q['id']+'.json'))['ranking']
        right=read(root/'bm25_bge_m3/traces'/(q['id']+'.json'))['fusion']['right']
        assert left==right, 'independent repeated BGE ranks differ'
    save(ARCHIVE/'audit/bge_repeatability.json',dict(questions=200,independent_process_ranks_exactly_equal=True,
        dense_only_actual_files=True,no_graph_or_scoring_reads=True,
        source_bindings={m:sha(root/m/'completed.json') for m in completed},script_sha256=sha(Path(__file__))))
    print('all200 independent BGE dense rankings exactly match fusion right branch; no graph/gold/sparse/colbert reads')

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--run-id',required=True);a=p.parse_args();main(a.run_id)
