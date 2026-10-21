"""Download pinned E5 weights and exact Qwen tokenizers, never questions/gold."""
import argparse
import hashlib
import json
import os
from pathlib import Path
from urllib.request import urlopen

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,v):
 p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--output',type=Path,required=True);p.add_argument('--cache',type=Path,required=True)
 p.add_argument('--tokenizers-only',action='store_true');a=p.parse_args()
 a.output.mkdir(parents=True,exist_ok=True)
 records={}
 for size in ('8B','14B'):
  name='Qwen/Qwen3-'+size;target=a.output/('qwen3-'+size.lower())
  binding=target/'artifact-binding.json'
  if binding.exists():
   row=json.loads(binding.read_text(encoding='utf-8'))
   assert all(sha(target/f)==h for f,h in row['files'].items())
   records[row['model']]=row;continue
  with urlopen('https://huggingface.co/api/models/'+name,timeout=120) as response:
   meta=json.load(response)
  revision=meta['sha'];target.mkdir(parents=True,exist_ok=True)
  for filename in ('tokenizer_config.json','tokenizer.json','vocab.json','merges.txt'):
   path=target/filename
   with urlopen(f'https://huggingface.co/{name}/resolve/{revision}/{filename}',timeout=180) as response:
    path.write_bytes(response.read())
  row={'model':'qwen3-'+size.lower(),'repository':name,'revision':revision,
       'files':{f:sha(target/f) for f in ('tokenizer_config.json','tokenizer.json','vocab.json','merges.txt')}}
  save(binding,row);records[row['model']]=row
  print(json.dumps({'tokenizer':row['model'],'revision':revision}),flush=True)
 save(a.output/'tokenizers.json',records)
 if not a.tokenizers_only:
  os.environ['HF_HUB_DISABLE_XET']='1'
  from huggingface_hub import snapshot_download
  spec=json.loads((Path(__file__).parent/'e5_small_model_spec.json').read_text(encoding='utf-8'))
  spec.pop('cache_folder',None)
  folder=Path(snapshot_download(repo_id=spec['model'],revision=spec['revision'],cache_dir=str(a.cache),
    allow_patterns=['*.json','*.txt','*.safetensors','1_Pooling/*']))
  save(a.output/'e5-artifact-binding.json',{**spec,'files':{f.relative_to(folder).as_posix():sha(f) for f in sorted(folder.rglob('*')) if f.is_file()}})
  save(a.output/'e5-runtime-spec.json',{**spec,'cache_folder':str(a.cache.resolve())})
  print(json.dumps({'e5_model':spec['model'],'revision':spec['revision']}),flush=True)

if __name__=='__main__':main()
