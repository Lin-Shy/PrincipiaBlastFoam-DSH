"""Current paths and source-only resource helpers."""
import hashlib,json,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent
PROJECT=HERE.parents[2]
WORKSPACE=PROJECT.parent
RESOURCES=WORKSPACE/'graduation-experiment-results/chapter2_retrieval/data/resources'
ARCHIVE=RESOURCES
GRAPH=RESOURCES/'graphs/selected.json'
DATASET=WORKSPACE/'graduation-datasets/chapter02_knowledge_qa'
QUESTIONS=DATASET/'open/model/questions.json'
sys.path[:0]=[str(PROJECT/'experiments/retrieval_method'),str(PROJECT/'src')]
def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for block in iter(lambda:f.read(4*1024*1024),b''):h.update(block)
 return h.hexdigest()
def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def wire(v):return json.dumps(v,ensure_ascii=False,separators=(',',':'),allow_nan=False)
def save(p,v):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
 with p.open('x',encoding='utf-8') as f:f.write(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
