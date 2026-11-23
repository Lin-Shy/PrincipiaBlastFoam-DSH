"""Package existing production domain tools and skills without tasks or scoring data."""
import argparse
import hashlib
import json
from pathlib import Path
import tarfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--project', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--cluster-project', type=Path)
args = parser.parse_args()
project = args.project.resolve(strict=True)
base = project / 'experiments/end2end'
files = {
    base / 'integrated_dev/pressure-tool.mjs': 'pressure-tool.mjs',
    base / 'integrated_dev/measurement-audit.mjs': 'measurement-audit.mjs',
    base / 'professional/observe.py': 'professional/observe.py',
    base / 'pressure_observations.py': 'pressure_observations.py',
    base / 'integrated_dev/engineering-delivery/SKILL.md': 'skills/engineering-delivery/SKILL.md',
    base / 'integrated_dev/measurement-review/SKILL.md': 'skills/measurement-review/SKILL.md',
    project / '.dsh/skills/blastfoam-quality-review/SKILL.md': 'skills/blastfoam-quality-review/SKILL.md',
}
if args.cluster_project:
    cluster = args.cluster_project.resolve(strict=True)
    files.update({cluster / 'scripts/hpc.py': 'cluster/scripts/hpc.py',
                  cluster / 'scripts/init_workspace.py': 'cluster/scripts/init_workspace.py',
                  cluster / 'simulation_authorization.json': 'cluster/simulation_authorization.json'})
assert not args.output.exists()
with tarfile.open(args.output, 'w:gz') as archive:
    for source, name in files.items():
        assert source.is_file() and not source.is_symlink()
        archive.add(source, arcname=name, recursive=False)
print(json.dumps({'archive': str(args.output), 'sha256': hashlib.sha256(args.output.read_bytes()).hexdigest(), 'files': len(files)}))
