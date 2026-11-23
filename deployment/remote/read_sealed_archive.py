"""Forced SSH command: read a sealed, verified archive at a bounded byte offset."""
import json
import os
from pathlib import Path
import re
import shlex
import sys

work = Path(__file__).resolve().parent
arguments = shlex.split(os.environ.get('SSH_ORIGINAL_COMMAND', ''))
if len(arguments) != 3 or arguments[0] != 'read-sealed' or not re.fullmatch(r'[a-z]+(?:-[a-z]+)*', arguments[1]) or not arguments[2].isdigit():
    raise SystemExit('Only read-sealed GROUP OFFSET is permitted')
name, offset = arguments[1], int(arguments[2])
receipt = json.loads((work / (name + '.sealed.json')).read_text())
path = work / receipt['cipher_file']
assert path.parent == work and path.resolve() == path and path.is_file() and not path.is_symlink()
assert path.stat().st_size == receipt['cipher_bytes'] and 0 <= offset <= receipt['cipher_bytes']
with path.open('rb') as stream:
    stream.seek(offset)
    while block := stream.read(1024**2):
        sys.stdout.buffer.write(block)
sys.stdout.buffer.flush()
