"""编码完成后、任何BGE题目检索前独立封存索引绑定；不改retrieval_v1。"""
import argparse
from common import *

def seal():
    index=ARCHIVE/'indexes/bge_dense_v1';m=read(index/'manifest.json')
    if m['model']!='BAAI/bge-m3' or m['revision']!='5617a9f61b028005a4858fdac845db406aefb181' or not m['dense_only'] or m['sparse'] or m['colbert']:
        raise ValueError('fixed BGE-M3 Dense index required')
    for name,h in m['files'].items():
        if sha(index/name)!=h:raise ValueError('BGE index drift before seal')
    save(ARCHIVE/'configs/bge_query_binding_v1.json',dict(status='sealed_before_any_bge_question_query',
        retrieval_protocol_sha256=sha(ARCHIVE/'configs/retrieval_v1.json'),
        index_manifest_sha256=sha(index/'manifest.json'),index_files=m['files'],
        official_model_binding_sha256=sha(ARCHIVE/'indexes/bge_model_binding.json'),
        model=m['model'],revision=m['revision'],dense_only=True,
        wrapper_sha256=sha(Path(__file__))))

def run(method,run_id,smoke):
    p=read(ARCHIVE/'configs/bge_query_binding_v1.json')
    if sha(Path(__file__))!=p['wrapper_sha256'] or sha(ARCHIVE/'indexes/bge_dense_v1/manifest.json')!=p['index_manifest_sha256'] or sha(ARCHIVE/'indexes/bge_model_binding.json')!=p['official_model_binding_sha256']:
        raise ValueError('BGE query input seal drift')
    if sha(ARCHIVE/'configs/retrieval_v1.json')!=p['retrieval_protocol_sha256']:raise ValueError('retrieval protocol drift')
    save(ARCHIVE/'audit/input_bindings'/(run_id+'_'+method+'.json'),dict(
        bge_query_binding_sha256=sha(ARCHIVE/'configs/bge_query_binding_v1.json'),run_id=run_id,method=method,smoke=smoke))
    from retrieval import run as retrieve
    retrieve(method,run_id,smoke)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['seal','run']);p.add_argument('--method',choices=['bge_m3','bm25_bge_m3'])
    p.add_argument('--run-id');p.add_argument('--smoke',action='store_true');a=p.parse_args()
    seal() if a.action=='seal' else run(a.method,a.run_id,a.smoke)
