"""Build E5 from the independently selected complete raw corpus only."""
import argparse
from dataclasses import asdict
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import sys
import time

PROJECT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(PROJECT/'src'))
from principia_core.retrieval.knowledge_qa import FrozenKnowledgeCorpus
from candidate_hybrid import passages,fit_tokens,model_load,local_snapshot

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--corpus',type=Path,required=True);p.add_argument('--manifest',type=Path,required=True)
 p.add_argument('--model-binding',type=Path,required=True);p.add_argument('--cache',type=Path,required=True)
 p.add_argument('--output',type=Path,required=True);a=p.parse_args()
 if a.output.exists():raise FileExistsError('a fresh index version directory is required')
 os.environ['HF_HUB_CACHE']=str(a.cache.resolve())
 from chapter2_knowledge_input_guard import install
 guard=install()
 corpus=FrozenKnowledgeCorpus(a.corpus,a.manifest)
 binding=json.loads(a.model_binding.read_text(encoding='utf-8'));spec={k:binding[k] for k in ('model','revision')}
 folder=local_snapshot(spec)
 assert all(sha(folder/name)==value for name,value in binding['files'].items()),'embedding weights drift'
 model=model_load(spec);docs=[]
 for name in sorted(corpus.hashes):
  lines=corpus.lines(name)
  raw=(a.corpus/name).read_bytes()
  for doc in passages(name,raw):docs.extend(fit_tokens(doc,model.tokenizer))
 a.output.mkdir(parents=True)
 save(a.output/'passages.json',docs)
 started=time.monotonic()
 vectors=model.encode(['passage: '+d['path']+'\n'+d['text'] for d in docs],normalize_embeddings=True,
   batch_size=32,show_progress_bar=True,convert_to_numpy=True)
 import numpy as np
 np.save(a.output/'embeddings.npy',vectors,allow_pickle=False)
 manifest={'schema':'independent_raw_corpus_e5_index_v1','model':spec,'model_files':binding['files'],
  'corpus_manifest_sha256':corpus.manifest_sha256,'corpus_files':corpus.hashes,'passages':len(docs),
  'embedding_dimensions':vectors.shape[1],'embedding_seconds':time.monotonic()-started,
  'passage_characters':1500,'overlap_lines':4,'max_sequence_length':512,
  'long_passage_policy':'recursively split full source lines to tokenizer limit; indivisible long lines recorded',
  'unavoidable_single_line_embedding_truncations':sum(d['embedding_single_line_truncated'] for d in docs),
  'prefixes':{'query':'query: ','passage':'passage: '},'text_input':'raw source and relative path only',
  'files':{name:sha(a.output/name) for name in ('passages.json','embeddings.npy')},
  'source_sha256':{p.name:sha(p) for p in (Path(__file__),Path(__file__).parent/'candidate_hybrid.py')},
  'packages':{name:importlib.metadata.version(name) for name in ('torch','numpy','transformers','sentence-transformers')},'guard':guard}
 save(a.output/'manifest.json',manifest)
 print(json.dumps({k:manifest[k] for k in ('passages','embedding_dimensions','embedding_seconds','unavoidable_single_line_embedding_truncations')}))

if __name__=='__main__':main()
