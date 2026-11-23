"""Candidate public exchange interface; preserves v1 registration wire format.

Deploy only in a newly frozen public task. It never assembles a delivery or
changes the operator's receipt, registered inputs, or recovered native files.
"""
import hashlib
import json
from pathlib import Path
import sys
import time

FILES = ("0/U", "0/p", "constant/transportProperties", "system/blockMeshDict",
         "system/controlDict", "system/fvSchemes", "system/fvSolution", "system/setFieldsDict")
SCHEMA = "c3-public-exchange-contract-v2"


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def registered_identity(request):
    if set(request) != set(FILES) or not all(isinstance(value, str) for value in request.values()):
        raise ValueError("Registration must contain exactly the eight input texts")
    return {name: digest(request[name].replace("\r\n", "\n").encode("utf8")) for name in FILES}


def describe_exchange(root, receipt=None):
    root = Path(root)
    request_path = root / "exchange/request.json"
    raw = request_path.read_bytes()
    request = json.loads(raw)
    registered = registered_identity(request)
    result = dict(schema=SCHEMA, state="registered" if receipt is None else "collected",
        registered_inputs=dict(content_source="exchange/request.json", current_workspace_source="case/",
            delivery_target="delivery/case/", hash_basis="UTF-8 registered text with CRLF normalized to LF",
            files=registered,
            identity_rule="Preserve registered input text except CRLF/LF differences; do not substitute node-written files, even if physically equivalent."),
        registration_json_sha256=digest(raw),
        required_delivery=dict(input_paths=["case/" + name for name in FILES], native_directory="native/",
            other_files=["receipt.json", "postprocess.py", "summary.json", "README.md"]),
        note="This describes file provenance and the public contract; it does not create a delivery or certify numerical correctness.")
    if receipt is not None:
        if receipt.get("input_sha256") != digest(raw):
            raise ValueError("Receipt does not identify this registered request")
        native_files = receipt.get("files")
        if not isinstance(native_files, dict) or not native_files:
            raise ValueError("Receipt has no native file identity map")
        if not all(isinstance(name, str) and isinstance(value, str) and len(value) == 64
                   and all(char in "0123456789abcdefABCDEF" for char in value)
                   for name, value in native_files.items()):
            raise ValueError("Invalid native SHA256 identity map")
        result["receipt_path"] = "exchange/receipt.json"
        result["recovered_native"] = dict(source_root="exchange/native/", delivery_target="delivery/native/",
            hash_basis="Original recovered file bytes", files=native_files,
            identity_rule="receipt.files refers to recovered native files, not submitted case/ inputs. Native initialization may rewrite 0/U and 0/p.")
        result["job"] = {key: receipt[key] for key in ("job_id", "scheduler", "exit_code") if key in receipt}
    return result


def submit(root):
    root = Path(root)
    payload = {name: (root / "case" / name).read_text(encoding="utf-8-sig") for name in FILES}
    exchange = root / "exchange"
    exchange.mkdir(exist_ok=True)
    with (exchange / "request.json").open("x", encoding="utf8") as handle:
        json.dump(payload, handle)
    result = describe_exchange(root)
    result["next_action"] = "collect; do not submit again"
    return result


def collect(root):
    root = Path(root)
    exchange = root / "exchange"
    for _ in range(55):
        if (exchange / "receipt.json").exists():
            return describe_exchange(root, json.loads((exchange / "receipt.json").read_bytes()))
        if (exchange / "failure.json").exists():
            raise RuntimeError((exchange / "failure.json").read_text())
        time.sleep(1)
    return dict(schema=SCHEMA, state="pending", next_action="repeat collect, never submit again")


if __name__ == "__main__":
    workspace = Path(__file__).resolve().parent.parent
    if len(sys.argv) != 2 or sys.argv[1] not in ("submit", "collect"):
        raise SystemExit("submit or collect")
    print(json.dumps({"submit": submit, "collect": collect}[sys.argv[1]](workspace), ensure_ascii=False, indent=2))
