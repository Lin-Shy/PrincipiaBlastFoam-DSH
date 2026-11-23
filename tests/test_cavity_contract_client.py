"""Exercise the public CLI with isolated data; never invokes a node or model."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

SOURCE = Path(__file__).resolve().parents[1] / "experiments/end2end/integrated_dev/cavity_agent"
INPUTS = ("0/U", "0/p", "constant/transportProperties", "system/blockMeshDict",
          "system/controlDict", "system/fvSchemes", "system/fvSolution", "system/setFieldsDict")


def workspace(tmp_path, name, client):
    root = tmp_path / name
    (root / "common").mkdir(parents=True)
    shutil.copyfile(SOURCE / client, root / "common/client.py")
    for item in INPUTS:
        path = root / "case" / item
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\xef\xbb\xbf// supplied input\r\nvalue 0;\r\n")
    return root


def call(root, action):
    return subprocess.run([sys.executable, "-X", "utf8", "common/client.py", action],
                          cwd=root, capture_output=True, text=True, encoding="utf8", timeout=10)


def test_registration_wire_format_and_duplicate_protection(tmp_path):
    old = workspace(tmp_path, "old", "client.py")
    new = workspace(tmp_path, "new", "contract_client.py")
    assert call(old, "submit").returncode == 0
    result = call(new, "submit")
    assert result.returncode == 0
    expected = (old / "exchange/request.json").read_bytes()
    assert (new / "exchange/request.json").read_bytes() == expected
    view = json.loads(result.stdout)
    assert set(view["registered_inputs"]["files"]) == set(INPUTS)
    assert view["registered_inputs"]["files"]["0/U"] == hashlib.sha256(b"// supplied input\nvalue 0;\n").hexdigest()
    assert call(new, "submit").returncode != 0
    assert (new / "exchange/request.json").read_bytes() == expected
    assert not (new / "delivery").exists()


def test_collect_distinguishes_native_hashes_without_modifying_artifacts(tmp_path):
    root = workspace(tmp_path, "view", "contract_client.py")
    assert call(root, "submit").returncode == 0
    native = root / "exchange/native/case/0/U"
    native.parent.mkdir(parents=True)
    native.write_bytes(b"// node-written header\nvalue 0;\n")
    receipt = dict(input_sha256=hashlib.sha256((root / "exchange/request.json").read_bytes()).hexdigest(),
                   files={"case/0/U": hashlib.sha256(native.read_bytes()).hexdigest()}, job_id="simulated-fixture", scheduler="COMPLETED", exit_code="0:0")
    (root / "exchange/receipt.json").write_text(json.dumps(receipt), encoding="utf8")
    before = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
    result = call(root, "collect")
    assert result.returncode == 0
    view = json.loads(result.stdout)
    assert view["recovered_native"]["source_root"] == "exchange/native/"
    assert view["registered_inputs"]["delivery_target"] == "delivery/case/"
    assert view["recovered_native"]["files"] == receipt["files"]
    assert view["registered_inputs"]["files"]["0/U"] != receipt["files"]["case/0/U"]
    assert "files" not in view
    assert {path: path.read_bytes() for path in root.rglob("*") if path.is_file()} == before
    assert "README.md" in view["required_delivery"]["other_files"]
    assert not (root / "delivery").exists()


def test_collect_rejects_receipt_from_another_request(tmp_path):
    root = workspace(tmp_path, "wrong", "contract_client.py")
    assert call(root, "submit").returncode == 0
    (root / "exchange/receipt.json").write_text(json.dumps(dict(input_sha256="0" * 64, files={"x": "1" * 64})))
    result = call(root, "collect")
    assert result.returncode != 0
    assert "does not identify this registered request" in result.stderr
    assert not (root / "delivery").exists()
