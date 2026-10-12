"""生产构图/检索进程的测试答案与数据设计读取防护。评分另用独立进程。"""
import os
from pathlib import Path
import sys


def install(*, offline=False, allow_test_public=False):
    """安装进程级Python审计防护；不能撤销，子进程必须另行安装。

    防护针对本实验Python实现的常见文件读取，不是操作系统安全沙箱。
    代码和依赖审计仍需独立进行，不能以此证明所有C扩展/外部命令不可读。
    """
    blocked = {"evaluation_only", "data_design"}
    if not allow_test_public:
        blocked.add("public_test")

    def guard(event, args):
        if event == "open" and args:
            raw = args[0]
            if isinstance(raw, (str, bytes, os.PathLike)):
                path = Path(os.fsdecode(raw)).resolve()
                if blocked.intersection(path.parts) or path.name.endswith(".annotations.json") or path.name == "annotations.json":
                    raise PermissionError("production process may not access evaluation gold or data-author artifacts")
        if offline and event in {"socket.connect", "socket.getaddrinfo"}:
            raise PermissionError("offline graph/retrieval process may not make network requests")
        if event in {"os.system", "subprocess.Popen"}:
            raise PermissionError("production evaluation process may not launch a subprocess to bypass input restrictions")

    sys.addaudithook(guard)
    return {"python_audit_hook": True, "blocked_path_components": sorted(blocked), "blocked_annotation_suffix": True,
            "network_disabled": offline, "subprocess_disabled": True, "limits": "Python-level enforcement; no operating-system sandbox claim"}
