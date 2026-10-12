"""完整候选与强无图对照共用的原文 BM25 / 多语种向量召回及融合。

索引仅源自冻结原文；图、题库、gold、留出文件不进入文本/向量索引。
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
import os
from pathlib import Path
import re
import time


def wire(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))


def sha(value):
    return hashlib.sha256(value if isinstance(value,bytes) else wire(value).encode()).hexdigest()


def tokens(text):
    identifiers=re.findall(r'[A-Za-z_][A-Za-z_0-9]*',text)
    split=re.findall(r'[A-Z]?[a-z]+|[A-Z]+(?=[A-Z]|$)|[0-9]+',' '.join(identifiers))
    chinese=[]
    for value in re.findall(r'[\u4e00-\u9fff]+',text):
        chinese.extend(value[i:i+2] for i in range(max(1,len(value)-1)))
    stop={'a','an','the','of','to','and','in','for','is','on','with','as','from'}
    return [t.casefold() for t in identifiers+split+chinese if t.casefold() not in stop]


def passages(path,raw,max_chars=1500,overlap=4):
    lines=raw.decode().splitlines()
    first=1
    while first<=len(lines):
        end=first-1;size=0
        while end<len(lines):
            if size+len(lines[end])>max_chars and end>=first:
                break
            size+=len(lines[end])+1;end+=1
        start=max(1,first-overlap)
        yield {'id':sha([sha(raw),path,start,end])[:24],'path':path,'start':start,'end':end,
               'source_sha256':sha(raw),'text':'\n'.join(lines[start-1:end])}
        first=end+1


# Transformer construction changes process-level initialization state. Guard both
# construction and inference so one arm cannot observe another arm's empty weights.
from threading import RLock
_MODEL_RUNTIME_LOCK = RLock()

def local_snapshot(spec):
    cache_root=Path(spec.get('cache_folder') or os.environ.get('HF_HUB_CACHE') or
                    Path.home()/'.cache/huggingface/hub')
    snapshot=cache_root/('models--'+spec['model'].replace('/','--'))/'snapshots'/spec['revision']
    if not snapshot.is_dir():
        raise FileNotFoundError('frozen embedding snapshot is unavailable: '+str(snapshot))
    return snapshot

def model_load(spec):
    with _MODEL_RUNTIME_LOCK:
        import torch
        torch.set_num_threads(4)
        from sentence_transformers import SentenceTransformer
        model=SentenceTransformer(str(local_snapshot(spec)),device='cpu',local_files_only=True)
        if any(p.is_meta for p in model.parameters()):raise ValueError('embedding model contains unmaterialized weights')
        model.max_seq_length=512
        return model


def fit_tokens(doc, tokenizer, limit=512):
    """Keep all source lines; split long passages rather than silently truncating them."""
    text='passage: '+doc['path']+'\n'+doc['text']
    size=len(tokenizer.encode(text,add_special_tokens=True,truncation=False))
    if size<=limit or doc['start']==doc['end']:
        yield {**doc,'embedding_input_tokens':size,'embedding_single_line_truncated':size>limit}
        return
    lines=doc['text'].splitlines()
    mid=(doc['start']+doc['end'])//2
    for a,b in [(doc['start'],mid),(mid+1,doc['end'])]:
        child={**doc,'id':sha([doc['source_sha256'],doc['path'],a,b])[:24],
               'start':a,'end':b,'text':'\n'.join(lines[a-doc['start']:b-doc['start']+1])}
        yield from fit_tokens(child,tokenizer,limit)


def build(archive,output,model_spec):
    if output.exists():
        raise FileExistsError('preserve frozen retrieval index')
    manifest=json.loads((archive/'corpus_manifest.json').read_text())
    docs=[]
    model=model_load(model_spec)
    for row in manifest['files']:
        raw=(archive/'corpus_native'/row['path']).read_bytes()
        if sha(raw)!=row['sha256']:
            raise ValueError('corpus changed')
        if row['utf8_text']:
            for doc in passages(row['path'],raw):
                docs.extend(fit_tokens(doc,model.tokenizer))
    output.mkdir(parents=True)
    (output/'passages.json').write_text(wire(docs))
    begin=time.monotonic()
    vectors=model.encode(['passage: '+d['path']+'\n'+d['text'] for d in docs],normalize_embeddings=True,
                         batch_size=32,show_progress_bar=True,convert_to_numpy=True)
    import numpy as np
    np.save(output/'embeddings.npy',vectors,allow_pickle=False)
    protocol={'schema':'candidate-shared-hybrid-v1','corpus_id':manifest['corpus_id'],
              'corpus_root':str((archive/'corpus_native').resolve()),'model':model_spec,'passages':len(docs),
              'embedding_dimensions':vectors.shape[1],'embedding_seconds':time.monotonic()-begin,
              'unavoidable_single_line_embedding_truncations':sum(d['embedding_single_line_truncated'] for d in docs),
              'text_index_input':'raw source and file path only; no graph or semantic relationships',
              'passage_characters':1500,'overlap_lines':4,'max_sequence_length':512,
              'prefixes':{'query':'query: ','passage':'passage: '},'parameters':{'bm25_k1':1.2,'bm25_b':.75,'rrf_k':60,'pool_per_retriever':64},
              'files':{name:sha((output/name).read_bytes()) for name in ['passages.json','embeddings.npy']},
              'source_code_sha256':sha(Path(__file__).read_bytes())}
    (output/'manifest.json').write_text(wire(protocol))
    return protocol


class Retriever:
    def __init__(self,index,semantic=True):
        self.root=index;self.manifest=json.loads((index/'manifest.json').read_text())
        for name,digest in self.manifest['files'].items():
            if sha((index/name).read_bytes())!=digest:
                raise ValueError('retrieval index changed')
        self.docs=json.loads((index/'passages.json').read_text())
        self.semantic=semantic
        self.counts=[Counter(tokens(d['path']+' '+d['text'])) for d in self.docs]
        self.lengths=[sum(c.values()) for c in self.counts]
        self.average=sum(self.lengths)/max(1,len(self.lengths))
        self.postings=defaultdict(list)
        for i,count in enumerate(self.counts):
            for term,frequency in count.items():self.postings[term].append((i,frequency))
        self.model=None;self.vectors=None
        if semantic:
            import numpy as np
            self.vectors=np.load(index/'embeddings.npy',allow_pickle=False)
            self.model=model_load(self.manifest['model'])
        self.queries={}

    def query(self,query,limit=32,case_scopes=(),seen_ids=(),semantic=None,mode=None):
        start=time.monotonic();work=Counter();rankings=[]
        if mode is None:
            mode='hybrid' if (self.semantic if semantic is None else semantic) else 'bm25'
        if mode not in {'bm25','vector','hybrid'}:
            raise ValueError('retrieval mode must be bm25, vector, or hybrid')
        active_semantic=mode in {'vector','hybrid'}
        if active_semantic and self.model is None:
            raise ValueError('semantic index not loaded')
        parameters=self.manifest['parameters'];pool=parameters['pool_per_retriever']
        n=len(self.docs)
        if mode in {'bm25','hybrid'}:
            weights=Counter()
            for term,qf in Counter(tokens(query)).items():
                posting=self.postings.get(term,[]);df=len(posting)
                idf=math.log(1+(n-df+.5)/(df+.5))
                for idx,tf in posting:
                    denom=tf+1.2*(1-.75+.75*self.lengths[idx]/max(1,self.average))
                    weights[idx]+=idf*(tf*2.2/denom)*min(qf,2)
                    work['bm25_posting_visits']+=1
            rankings.append(sorted(weights,key=lambda i:(-weights[i],self.docs[i]['id']))[:pool])
        if active_semantic:
            import numpy as np
            if query not in self.queries:
                with _MODEL_RUNTIME_LOCK:
                    self.queries[query]=self.model.encode(['query: '+query],normalize_embeddings=True,convert_to_numpy=True)[0]
                work['query_embeddings_computed']+=1
            scores=self.vectors@self.queries[query]
            rankings.append(sorted(range(n),key=lambda i:(-float(scores[i]),self.docs[i]['id']))[:pool])
            work['dense_dot_products']+=n
        # Literal identifiers are part of the lexical comparator/hybrid only;
        # vector mode remains a genuine dense-only baseline.
        if mode in {'bm25','hybrid'}:
            exact=re.findall(r'[A-Za-z_][A-Za-z_0-9./-]*',query)
            exact_score={i:sum((4 if t in d['path'] else 1) for t in exact if t in d['path'] or re.search(r'(?<!\w)'+re.escape(t)+r'(?!\w)',d['text'])) for i,d in enumerate(self.docs)}
            rankings.append(sorted((i for i,v in exact_score.items() if v),key=lambda i:(-exact_score[i],self.docs[i]['id']))[:pool])
        fused=Counter()
        for ranking in rankings:
            for rank,idx in enumerate(ranking,1):fused[idx]+=1/(parameters['rrf_k']+rank)
        seen=set(seen_ids)
        eligible=[]
        for idx,score in fused.items():
            d=self.docs[idx]
            if d['id'] in seen:continue
            if case_scopes and d['path'].startswith('tutorials/') and not any(d['path'].startswith(c.rstrip('/')+'/') for c in case_scopes):
                continue
            eligible.append((idx,score))
        eligible.sort(key=lambda row:(-row[1],self.docs[row[0]]['id']))
        picked=[]
        for idx,score in eligible:
            d=self.docs[idx]
            # Suppress overlap, not another source or a complementary remote passage.
            duplicate=any(d['path']==p['path'] and max(0,min(d['end'],p['end'])-max(d['start'],p['start'])+1)/max(1,min(d['end']-d['start']+1,p['end']-p['start']+1))>.75 for p in picked)
            if not duplicate:picked.append({**d,'score':score})
            if len(picked)>=limit:break
        return picked,{'seconds':time.monotonic()-start,'work':dict(work),'semantic_enabled':active_semantic,
                       'retrieval_mode':mode,
                       'candidate_counts':[len(r) for r in rankings],'fused_candidates':len(fused),'returned':len(picked)}


if __name__=='__main__':
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--archive',type=Path,required=True)
    cli.add_argument('--output',type=Path,required=True)
    cli.add_argument('--model-spec',type=Path,required=True)
    args=cli.parse_args()
    print(wire(build(args.archive.resolve(),args.output.resolve(),json.loads(args.model_spec.read_text()))))
