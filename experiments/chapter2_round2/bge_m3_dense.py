"""固定 BAAI/bge-m3：CLS、L2 单向量；不加载 Sparse/ColBERT 权重。"""
import argparse
import importlib.metadata
import os
import time

from common import *
from download_bge import SNAPSHOT, REVISION
from text_baselines import BM25

class DenseEncoder:
    def __init__(self):
        os.environ['HF_HUB_OFFLINE']='1'
        os.environ['TRANSFORMERS_OFFLINE']='1'
        import torch
        from transformers import AutoModel,AutoTokenizer
        torch.set_num_threads(4)
        torch.manual_seed(20261020)
        torch.use_deterministic_algorithms(True)
        binding=read(ARCHIVE/'indexes/bge_model_binding.json')
        if binding['model']!='BAAI/bge-m3' or binding['revision']!=REVISION:
            raise ValueError('only fixed official BGE-M3 permitted')
        if any(sha(SNAPSHOT/name)!=v for name,v in binding['files'].items()):
            raise ValueError('BGE model snapshot drift')
        self.tokenizer=AutoTokenizer.from_pretrained(str(SNAPSHOT),local_files_only=True,trust_remote_code=False)
        self.model=AutoModel.from_pretrained(str(SNAPSHOT),local_files_only=True,trust_remote_code=False).float().eval()
        if self.model.config.hidden_size!=1024:raise ValueError('BGE-M3 hidden dimension mismatch')
        self.torch=torch

    def encode(self,texts,batch_size=4):
        import numpy as np
        vectors=[]
        for start in range(0,len(texts),batch_size):
            batch=self.tokenizer(texts[start:start+batch_size],padding=True,truncation=True,max_length=8192,return_tensors='pt')
            with self.torch.inference_mode():
                outputs=self.model(**batch)
                dense=self.torch.nn.functional.normalize(outputs.last_hidden_state[:,0],p=2,dim=1)
                vectors.append(dense.cpu().numpy())
        return np.concatenate(vectors,axis=0)

def build():
    from chapter2_knowledge_input_guard import install
    install()
    target=ARCHIVE/'indexes/bge_dense_v1'
    target.mkdir(parents=True,exist_ok=False)
    started=time.monotonic();bm25=BM25();encoder=DenseEncoder()
    docs=bm25.docs
    texts=[d['path']+'\n'+d['text'] for d in docs]
    lengths=[len(encoder.tokenizer.encode(t,add_special_tokens=True,truncation=False)) for t in texts]
    for d,n in zip(docs,lengths):d.update(embedding_input_tokens=n,embedding_truncated=n>8192)
    save(target/'passages.json',docs)
    # One nonformal public-source batch estimates local runtime before full indexing.
    begin=time.monotonic();encoder.encode(texts[:4]);probe=time.monotonic()-begin
    print(wire(dict(passages=len(docs),probe4_seconds=probe,rough_total_seconds=probe*len(docs)/4,
                    max_input_tokens=max(lengths),truncated=sum(n>8192 for n in lengths))),flush=True)
    chunks=[]
    for i in range(0,len(texts),32):
        chunks.append(encoder.encode(texts[i:i+32]))
        if i%128==0:print('encoded',min(i+32,len(texts)),'/',len(texts),'seconds',round(time.monotonic()-started,1),flush=True)
    import numpy as np
    np.save(target/'embeddings.npy',np.concatenate(chunks,axis=0),allow_pickle=False)
    save(target/'manifest.json',dict(model='BAAI/bge-m3',revision=REVISION,dense_only=True,sparse=False,colbert=False,
        device='cpu',dtype='float32',pooling='CLS_L2_normalized',max_length=8192,batch_size=4,
        query_prefix='',document_input='path + newline + raw text',passages=len(docs),dimensions=1024,
        tokenizer_truncated_passages=sum(n>8192 for n in lengths),max_input_tokens=max(lengths),
        corpus_manifest_sha256=sha(RESOURCES/'source-map.json'),model_binding_sha256=sha(ARCHIVE/'indexes/bge_model_binding.json'),
        bm25_chunk_identity='exact shared historical NoGraphBM25 partition; 1500 nominal chars + 4 preceding lines',
        files={n:sha(target/n) for n in ['passages.json','embeddings.npy']},build_seconds=time.monotonic()-started,
        packages={n:importlib.metadata.version(n) for n in ['torch','transformers','numpy']},
        source_sha256=sha(Path(__file__))))

class BGEDense:
    def __init__(self):
        start=time.monotonic()
        import numpy as np
        self.index=ARCHIVE/'indexes/bge_dense_v1';m=read(self.index/'manifest.json')
        if m['model']!='BAAI/bge-m3' or not m['dense_only'] or m['sparse'] or m['colbert']:
            raise ValueError('Dense only BGE-M3 index required')
        if m['corpus_manifest_sha256']!=sha(RESOURCES/'source-map.json'):
            raise ValueError('BGE corpus manifest drift')
        if any(sha(self.index/n)!=h for n,h in m['files'].items()):raise ValueError('BGE index drift')
        if m['model_binding_sha256']!=sha(ARCHIVE/'indexes/bge_model_binding.json'):raise ValueError('BGE binding drift')
        self.docs=read(self.index/'passages.json');self.vectors=np.load(self.index/'embeddings.npy',allow_pickle=False)
        hashes=read(RESOURCES/'source-map.json')['files']
        if any(hashes.get(d['path'])!=d['source_sha256'] for d in self.docs):raise ValueError('BGE passage authority drift')
        if self.vectors.shape!=(len(self.docs),1024):raise ValueError('BGE vector shape mismatch')
        self.encoder=DenseEncoder();self.load_seconds=time.monotonic()-start

    def rank(self,query,limit=64):
        vector=self.encoder.encode([query])[0];scores=self.vectors@vector
        order=sorted(range(len(self.docs)),key=lambda i:(-float(scores[i]),self.docs[i]['id']))[:limit]
        return [dict(path=self.docs[i]['path'],start=self.docs[i]['start'],end=self.docs[i]['end'],
                     native_unit=self.docs[i]['id'],score=float(scores[i]),native_rank=rank)
                for rank,i in enumerate(order,1)]

if __name__=='__main__':
    build()
