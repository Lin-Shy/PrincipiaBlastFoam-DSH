"""评分进程的连接中断适配：转换为原网络重试分支，尝试上限保持不变。"""
import argparse
import hashlib
import http.client
import json
from pathlib import Path
import runpy
import sys
import time
import urllib.error
import urllib.request


def guarded_open(original, folder):
    interrupted = (http.client.RemoteDisconnected, ConnectionResetError, BrokenPipeError)

    def record(exc, request):
        folder.mkdir(parents=True, exist_ok=True)
        data = getattr(request, "data", None) or b""
        value = {"error_type": type(exc).__name__, "signal": "connection_interrupted",
                 "request_sha256": hashlib.sha256(data).hexdigest(), "usage_unknown": True}
        path = folder / f"{time.time_ns()}.json"
        with path.open("x") as stream:
            json.dump(value, stream)

    def open_request(request, *args, **kwargs):
        try:
            response = original(request, *args, **kwargs)
        except interrupted as exc:
            record(exc, request)
            raise urllib.error.URLError(exc) from None

        class Response:
            def __enter__(self):
                response.__enter__()
                return self

            def __exit__(self, *args):
                return response.__exit__(*args)

            def __getattr__(self, name):
                return getattr(response, name)

            def read(self, *args, **kwargs):
                try:
                    return response.read(*args, **kwargs)
                except interrupted as exc:
                    record(exc, request)
                    raise urllib.error.URLError(exc) from None

        return Response()

    return open_request


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--revision", type=Path, required=True)
    p.add_argument("--entry", type=Path, required=True)
    p.add_argument("arguments", nargs=argparse.REMAINDER)
    args = p.parse_args()
    revision, entry = args.revision.resolve(), args.entry.resolve()
    spec = json.loads((revision / "connection_guard_amendment_001.json").read_text())
    if spec["script_sha256"] != hashlib.sha256(Path(__file__).read_bytes()).hexdigest() or spec["entry_sha256"] != hashlib.sha256(entry.read_bytes()).hexdigest():
        raise ValueError("connection adapter binding drift")
    urllib.request.urlopen = guarded_open(urllib.request.urlopen, revision / "connection_exception_events")
    forwarded = args.arguments[1:] if args.arguments and args.arguments[0] == "--" else args.arguments
    sys.argv = [str(entry), *forwarded]
    runpy.run_path(str(entry), run_name="__main__")


if __name__ == "__main__":
    main()
