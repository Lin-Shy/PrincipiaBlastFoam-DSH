"""Package frozen first-party DSH code, reinstall dependencies on Linux.

No model configuration, research data, external node_modules or keys are packed.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import tarfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('snapshot', type=Path)
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    snapshot = args.snapshot.resolve()
    manifest = json.loads((snapshot / 'snapshot.json').read_bytes())
    packages = {p['path']: p for p in manifest['packages']}
    internal = {p: row for p, row in packages.items() if not p.startswith('node_modules/')}
    edges = {}
    for link in manifest['links']:
        parent, dependency = link['path'].rsplit('/node_modules/', 1)
        edges[parent, dependency] = packages[link['target']]
    args.destination.mkdir(parents=True, exist_ok=False)
    stage = args.destination / 'source'
    stage.mkdir()
    pins = {}
    for row in manifest['files']:
        relative = row['path']
        if relative.startswith('node_modules/'):
            continue
        source = snapshot / relative
        raw = source.read_bytes()
        if hashlib.sha256(raw).hexdigest() != row['sha256']:
            raise ValueError('Frozen source mismatch: ' + relative)
        target = stage / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        pins[relative] = row['sha256']
    adaptations = []
    for relative, package in internal.items():
        target = stage / relative / 'package.json'
        original = json.loads(target.read_bytes())
        value = copy.deepcopy(original)
        value.pop('devDependencies', None)
        value.pop('scripts', None)
        for field in ('dependencies', 'optionalDependencies'):
            for name in value.get(field, {}):
                resolved = edges.get((relative, name))
                if resolved:
                    value[field][name] = ('workspace:*' if resolved['path'] in internal else resolved['version'])
        # Optional/peer platform variants not installed on Windows retain their
        # original declared ranges so pnpm can resolve the Linux binary.
        target.write_text(json.dumps(value, indent=2) + '\n', encoding='utf8')
        adaptations.append(relative + '/package.json')
    root = {'name': 'chapter3-linux-controller', 'private': True,
            'packageManager': 'pnpm@11.7.0', 'engines': {'node': '>=24'},
            'dependencies': {'@deepseek-ai/dsh': 'workspace:*'}}
    (stage / 'package.json').write_text(json.dumps(root, indent=2) + '\n', encoding='utf8')
    workspace = {'packages': sorted(internal), 'linkWorkspacePackages': True,
                 'allowBuilds': {'fs-ext': True, 'koffi': True, 'node-pty': True,
                                 'esbuild': True, 'node-addon-require-builtin': False,
                                 'protobufjs': False, '@google/genai': False},
                 'minimumReleaseAge': 0}
    # JSON is valid YAML; no YAML library is needed during packaging.
    (stage / 'pnpm-workspace.yaml').write_text(json.dumps(workspace, indent=2) + '\n', encoding='utf8')
    (stage / 'SOURCE_BINDING.json').write_text(json.dumps({
        'identity': 'Linux deployment candidate derived from frozen installed snapshot; not byte-identical cross-platform runtime',
        'snapshot_sha256': hashlib.sha256((snapshot / 'snapshot.json').read_bytes()).hexdigest(),
        'original_source_sha256': pins, 'adapted_manifests': adaptations,
        'external_dependencies': 'Reinstalled on Linux; transitive resolution recorded by new lockfile',
        'model_calls': 0, 'node_jobs': 0}, indent=2) + '\n', encoding='utf8')
    archive = args.destination / 'controller-source.tar.gz'
    with tarfile.open(archive, 'w:gz') as out:
        out.add(stage, arcname='source')
    print(json.dumps({'archive': str(archive.resolve()), 'bytes': archive.stat().st_size,
                      'sha256': hashlib.sha256(archive.read_bytes()).hexdigest(),
                      'first_party_packages': len(internal)}))


if __name__ == '__main__':
    main()
