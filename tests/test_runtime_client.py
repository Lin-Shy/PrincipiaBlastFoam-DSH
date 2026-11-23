"""Runtime metadata must be available before registration without changing wire bytes."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import pytest

SOURCE = Path(__file__).resolve().parents[1] / 'experiments/end2end/integrated_dev'
FILES = ('0/U', '0/p', 'constant/transportProperties', 'system/blockMeshDict',
    'system/controlDict', 'system/fvSchemes', 'system/fvSolution', 'system/setFieldsDict')


@pytest.fixture
def workspace(tmp_path):
    (tmp_path / 'common').mkdir()
    (tmp_path / 'runtime').mkdir()
    for source, target in [(SOURCE / 'startup_couette/runtime_client.py', 'client.py'),
        (SOURCE / 'startup_couette/runtime_info.py', 'runtime_info.py'),
        (SOURCE / 'cavity_agent/contract_client.py', 'contract_client.py')]:
        shutil.copyfile(source, tmp_path / 'common' / target)
    raw = b'{"schema":"c3-openfoam-public-runtime-v1","version":"fixture-only"}'
    (tmp_path / 'runtime/RUNTIME.json').write_bytes(raw)
    (tmp_path / 'common/runtime-binding.json').write_text(json.dumps({'sha256': hashlib.sha256(raw).hexdigest()}))
    for name in FILES:
        file = tmp_path / 'case' / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(b'fixture\r\n')
    return tmp_path


def invoke(root, action):
    return subprocess.run([sys.executable, '-B', str(root / 'common/client.py'), action],
        capture_output=True, text=True, timeout=10)


def test_runtime_does_not_register_and_submit_collect_keep_wire(workspace):
    root = workspace
    metadata = invoke(root, 'runtime')
    assert metadata.returncode == 0 and json.loads(metadata.stdout)['runtime']['version'] == 'fixture-only'
    assert not (root / 'exchange').exists()
    submitted = invoke(root, 'submit')
    assert submitted.returncode == 0
    wire = (root / 'exchange/request.json').read_bytes()
    assert wire == json.dumps({name: 'fixture\n' for name in FILES}).encode()
    view = json.loads(submitted.stdout)
    assert 'profile.csv' in view['required_delivery']['other_files']
    receipt = {'input_sha256': hashlib.sha256(wire).hexdigest(), 'files': {'case/0/U': 'a' * 64}}
    (root / 'exchange/receipt.json').write_text(json.dumps(receipt))
    collected = invoke(root, 'collect')
    assert collected.returncode == 0 and json.loads(collected.stdout)['recovered_native']['files'] == receipt['files']
    assert (root / 'exchange/request.json').read_bytes() == wire
    assert invoke(root, 'submit').returncode != 0
    assert not (root / 'delivery').exists()


def test_changed_runtime_rejected_before_registration(workspace):
    (workspace / 'runtime/RUNTIME.json').write_text('{}')
    result = invoke(workspace, 'submit')
    assert result.returncode != 0 and not result.stdout
    assert not (workspace / 'exchange').exists()
