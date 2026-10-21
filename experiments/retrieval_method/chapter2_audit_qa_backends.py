"""Deterministically audit original-source delivery for independent QA backends."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

PROJECT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(PROJECT/'src'))
from principia_core.retrieval.knowledge_qa import FrozenKnowledgeCorpus,KnowledgeToolSession,KnowledgeBudget
from chapter2_qa_backends import create_backend

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--corpus',type=Path,required=True);p.add_argument('--manifest',type=Path,required=True)
 p.add_argument('--source-map',type=Path,required=True);p.add_argument('--e5-index',type=Path,required=True)
 p.add_argument('--cache',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
 a=p.parse_args();os.environ['HF_HUB_CACHE']=str(a.cache.resolve())
 from chapter2_knowledge_input_guard import install
 guard=install();corpus=FrozenKnowledgeCorpus(a.corpus,a.manifest)
 assert json.loads(a.source_map.read_text(encoding='utf-8'))['files']==corpus.hashes
 records=[]
 for method in ('bm25','e5','hybrid'):
  backend=create_backend(method,a.corpus,a.source_map,e5_index=a.e5_index)
  session=KnowledgeToolSession(method,corpus,backend,KnowledgeBudget())
  for query in ('fieldValue delta AMR pressure','pressure impulse blast function object'):
   packet=json.loads(session.execute('search',{'query':query}))
   assert packet['evidence'],'no usable original passage returned'
   for unit in packet['evidence']:
    original=corpus.lines(unit['path'])
    assert unit['sha256']==corpus.hashes[unit['path']]
    assert all(line['text']==original[line['number']-1] for line in unit['lines'])
  assert all(e['status']=='returned' and e['delivered_characters']<=6000 for e in session.events)
  assert session.characters==sum(e['delivered_characters'] for e in session.events)<=24000
  records.append({'method':method,'passed':True,'events':session.events,'native_rankings':backend.events})
  print(json.dumps({'method':method,'passed':True,'knowledge_characters':session.characters}),flush=True)
 result={'schema':'independent_qa_backend_delivery_audit_v1','passed':True,'model_calls':0,
    'corpus_manifest_sha256':sha(a.manifest),'source_map_sha256':sha(a.source_map),
    'e5_manifest_sha256':sha(a.e5_index/'manifest.json'),'implementation_sha256':sha(Path(__file__)),
    'guard':guard,'records':records,'limits':['Checks source identity and delivery budget, not ranking/answer quality.','Graph backend is not included until its construction/ablation audit is complete.']}
 a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

if __name__=='__main__':main()
