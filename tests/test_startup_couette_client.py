"""The public client must name the new profile artifact without changing wire data."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "experiments/end2end/integrated_dev"


def test_startup_cli_exposes_profile_in_both_receipt_views(tmp_path):
    common = tmp_path / "common"
    common.mkdir()
    shutil.copyfile(SOURCE / "startup_couette/client.py", common / "client.py")
    shutil.copyfile(SOURCE / "cavity_agent/contract_client.py", common / "contract_client.py")
    names = ("0/U", "0/p", "constant/transportProperties", "system/blockMeshDict",
             "system/controlDict", "system/fvSchemes", "system/fvSolution", "system/setFieldsDict")
    for name in names:
        path = tmp_path / "case" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"test dictionary\r\n")
    run = lambda action: subprocess.run([sys.executable, str(common / "client.py"), action],
                                        capture_output=True, text=True, check=True)
    registered = json.loads(run("submit").stdout)
    expected_other = {"receipt.json", "postprocess.py", "summary.json", "README.md", "profile.csv"}
    assert set(registered["required_delivery"]["other_files"]) == expected_other
    request = tmp_path / "exchange/request.json"
    wire = request.read_bytes()
    assert wire == json.dumps({name: "test dictionary\n" for name in names}).encode()
    receipt = {"input_sha256": hashlib.sha256(wire).hexdigest(),
               "files": {"case/0/U": hashlib.sha256(b"synthetic native bytes").hexdigest()},
               "job_id": "fixture-only", "scheduler": "COMPLETED", "exit_code": "0:0"}
    (tmp_path / "exchange/receipt.json").write_text(json.dumps(receipt), encoding="utf8")
    collected = json.loads(run("collect").stdout)
    assert set(collected["required_delivery"]["other_files"]) == expected_other
    assert collected["recovered_native"]["files"] == receipt["files"]
    assert request.read_bytes() == wire
    assert not (tmp_path / "delivery").exists()
