"""Local, model-specific chat tokenization. No hub access or approximate counts."""
from pathlib import Path
import hashlib,json,threading
from models import EXPERIMENT,MODELS,encoded,sha

ROOT=EXPERIMENT/'data/resources/tokenizers'

class ChatCounter:
    def __init__(self,model):
        if model not in MODELS:raise ValueError('Unregistered tokenizer')
        from transformers import AutoTokenizer
        self.model=model;self.root=ROOT/model;self.lock=threading.Lock()
        self.files={p.name:sha(p.read_bytes()) for p in sorted(self.root.glob('*.json')) if p.name!='provenance.json'}
        if not {'tokenizer.json','tokenizer_config.json'}<=self.files.keys():raise ValueError('Incomplete tokenizer')
        self.tokenizer=AutoTokenizer.from_pretrained(str(self.root),local_files_only=True,trust_remote_code=False)
        if not self.tokenizer.chat_template:raise ValueError('Missing model chat template')
        self.binding=sha(encoded(dict(model=model,files=self.files,add_generation_prompt=True)))

    def ids(self,messages):
        kwargs={'enable_thinking':False} if self.model=='qwen3-14b' else {}
        # All actual payloads are counted after model routing directives are added.
        with self.lock:
            return self.tokenizer.apply_chat_template(messages,tokenize=True,add_generation_prompt=True,**kwargs)

    def __call__(self,messages):return len(self.ids(messages))

    def public(self):return dict(model=self.model,tokenizer_sha256=self.binding,files=self.files,local_only=True,add_generation_prompt=True)
