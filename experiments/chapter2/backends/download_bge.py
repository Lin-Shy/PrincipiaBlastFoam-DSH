"""仅公开 GET；不携带账号 token，不上传本地数据。"""
import json
from pathlib import Path
import urllib.request
from common import ARCHIVE, PROJECT, save, sha

REVISION = '5617a9f61b028005a4858fdac845db406aefb181'
FILES = ['1_Pooling/config.json', 'config.json', 'config_sentence_transformers.json',
         'modules.json', 'pytorch_model.bin', 'sentence_bert_config.json',
         'sentencepiece.bpe.model', 'special_tokens_map.json', 'tokenizer.json',
         'tokenizer_config.json', 'README.md']
SNAPSHOT = PROJECT / '.local/chapter2-round2-models/BAAI--bge-m3' / REVISION

def main():
    url = f'https://huggingface.co/api/models/BAAI/bge-m3/tree/{REVISION}?recursive=true&expand=false'
    with urllib.request.urlopen(url, timeout=30) as response:
        tree = json.load(response)
    by_path = {r['path']: r for r in tree}
    for name in FILES:
        target = SNAPSHOT / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            raise FileExistsError('new download required; do not silently reuse incomplete snapshot')
        print('download', name, 'bytes', by_path[name]['size'], flush=True)
        with urllib.request.urlopen(f'https://huggingface.co/BAAI/bge-m3/resolve/{REVISION}/{name}', timeout=60) as response, target.open('xb') as out:
            while chunk := response.read(1024*1024):
                out.write(chunk)
        if target.stat().st_size != by_path[name]['size']:
            raise ValueError('model download size mismatch')
        if 'lfs' in by_path[name] and sha(target) != by_path[name]['lfs']['oid']:
            raise ValueError('official LFS model hash mismatch')
    save(ARCHIVE / 'indexes/bge_model_binding.json', dict(model='BAAI/bge-m3', revision=REVISION,
         files={name: sha(SNAPSHOT/name) for name in FILES},
         downloaded_bytes=sum((SNAPSHOT/n).stat().st_size for n in FILES),
         model_card='https://huggingface.co/BAAI/bge-m3',
         dense_only=True, sparse=False, colbert=False, official_tree=tree))
    print('complete', flush=True)

if __name__ == '__main__':
    main()
