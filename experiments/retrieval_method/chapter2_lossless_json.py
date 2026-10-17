"""Atomic JSON persistence preserving even unpaired surrogate code points."""
import json
from pathlib import Path

POLICY = 'atomic_json_surrogate_escape_v1'


def encode(value):
    # Backslash escaping is reversible JSON, not a replacement character or repair.
    return json.dumps(value, ensure_ascii=False, indent=2).encode('utf-8', 'backslashreplace')


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.lossless.tmp')
    with temporary.open('xb') as stream:
        stream.write(encode(value))
    temporary.replace(path)
