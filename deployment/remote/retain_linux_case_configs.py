"""Copy bounded, manifest-verified case inputs before historical roots are retired."""
import argparse
import bisect
import hashlib
import json
import os
from pathlib import Path
import shutil

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--work', type=Path, required=True)
parser.add_argument('--destination', type=Path, required=True)
args = parser.parse_args()
destination = args.destination.resolve()
destination.mkdir(mode=0o700, parents=True, exist_ok=False)
objects = destination / '.objects'
objects.mkdir()
stored = set()
index = {'schema': 'retained-case-configs-v2', 'cases': [], 'bytes': 0, 'logical_bytes': 0,
         'policy': 'system, constant except generated polyMesh, and initial fields; no result times; large inputs remain in Windows archive'}
for manifest_path in sorted(args.work.glob('*.manifest.json')):
    manifest = json.loads(manifest_path.read_text())
    rows = {row['path']: row for row in manifest['entries']}
    names = sorted(rows)
    cases = sorted(path[:-len('/system/controlDict')] for path in rows if path.endswith('/system/controlDict'))
    for case in cases:
        identity = hashlib.sha256(case.encode()).hexdigest()[:20]
        record = {'source': '/' + case, 'archive_group': manifest['name'], 'directory': identity, 'copied': [], 'omitted': []}
        start = bisect.bisect_left(names, case + '/')
        for name in names[start:]:
            if not name.startswith(case + '/'):
                break
            row = rows[name]
            relative = name[len(case) + 1:]
            parts = Path(relative).parts
            if not parts or parts[0] not in ('system', 'constant', '0', '0.orig', '0.org', '0.template') or 'polyMesh' in parts:
                continue
            if row['type'] == 'directory':
                continue
            if row['type'] != 'file' or row['size'] > 1024**2 or (row.get('sha256') not in stored and index['bytes'] + row.get('size', 0) > 256 * 1024**2):
                record['omitted'].append({'path': relative, 'reason': 'symlink/special or input size limit; original retained in archive'})
                continue
            source = Path('/' + name)
            target = destination / identity / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if row['sha256'] not in stored:
                assert hashlib.sha256(source.read_bytes()).hexdigest() == row['sha256'], str(source)
                blob = objects / row['sha256']
                shutil.copyfile(source, blob)
                blob.chmod(0o600)
                assert hashlib.sha256(blob.read_bytes()).hexdigest() == row['sha256']
                stored.add(row['sha256'])
                index['bytes'] += row['size']
            os.link(objects / row['sha256'], target)
            record['copied'].append({'path': relative, 'sha256': row['sha256'], 'size': row['size']})
            index['logical_bytes'] += row['size']
        index['cases'].append(record)
(destination / 'index.json').write_text(json.dumps(index, indent=2))
print(json.dumps({'cases': len(index['cases']), 'bytes': index['bytes'], 'destination': str(destination)}))
