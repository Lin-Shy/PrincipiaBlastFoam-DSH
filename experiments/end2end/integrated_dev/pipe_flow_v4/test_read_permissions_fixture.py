"""Offline Windows DACL regression using only temporary harmless fixture files.

The test uses an ordinary restricted token for filesystem operations on the
current thread. It does not launch DSH, start subprocesses under the token, or
change permissions on any existing run, account, binary, or host directory.
"""
import json
import pkgutil  # runpy dependency loaded before thread impersonation
import runpy
import tempfile
import uuid
from pathlib import Path

import ntsecuritycon
import win32api
import win32con
import win32security as security


def grant_fixture(path, sid, mask):
    flags = security.DACL_SECURITY_INFORMATION
    acl = security.GetNamedSecurityInfo(str(path), security.SE_FILE_OBJECT, flags).GetSecurityDescriptorDacl()
    inherit = (win32con.CONTAINER_INHERIT_ACE | win32con.OBJECT_INHERIT_ACE) if path.is_dir() else 0
    acl.AddAccessAllowedAceEx(security.ACL_REVISION, inherit, mask, sid)
    security.SetNamedSecurityInfo(str(path), security.SE_FILE_OBJECT, flags, None, None, acl, None)


def inaccessible(operation):
    try:
        operation()
    except PermissionError:
        return True
    return False


def exercise():
    with tempfile.TemporaryDirectory(prefix="pipe-read-policy-") as temp:
        base = Path(temp)
        arms = ("general", "professional")
        # Independent restricting identities, unconnected to host accounts.
        sids = {}
        for arm in arms:
            sids[arm] = security.ConvertStringSidToSid("S-1-5-21-" + "-".join(str(int.from_bytes(uuid.uuid4().bytes[:4], "little")) for _ in range(3)) + "-1001")
            ws = base / arm / "workspace"
            for name in ("common", "pipe_exchange", "delivery"):
                (ws / name).mkdir(parents=True)
            for path in (base / arm / "operator.txt", ws / "TASK.md", ws / "common" / "tool.txt",
                         ws / "pipe_exchange" / "profile.csv", ws / "delivery" / "report.txt"):
                path.write_text("fixture", encoding="ascii")
            client = ws / "common" / "client.py"
            client.write_text("def submit(work):\n    data = (work / 'pipe_exchange/profile.csv').read_bytes()\n    (work / 'delivery/new.txt').write_bytes(data)\n", encoding="ascii")
            for p in [ws, *ws.rglob("*")]:
                mask = ntsecuritycon.FILE_GENERIC_READ | ntsecuritycon.FILE_GENERIC_EXECUTE
                if p == ws / "delivery" or ws / "delivery" in p.parents:
                    mask |= ntsecuritycon.FILE_GENERIC_WRITE
                grant_fixture(p, sids[arm], mask)
        token = security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_DUPLICATE | win32con.TOKEN_QUERY)
        results = {}
        for arm in arms:
            ws = base / arm / "workspace"
            other = next(a for a in arms if a != arm)
            restricted = security.CreateRestrictedToken(token, 1, [], [], [(sids[arm], 0)])
            security.ImpersonateLoggedOnUser(restricted)
            try:
                checks = {str(p.relative_to(ws)):p.read_text(encoding="ascii") == "fixture" for p in
                          [ws/"TASK.md", ws/"common/tool.txt", ws/"pipe_exchange/profile.csv"]}
                client = runpy.run_path(str(ws/"common/client.py"))
                client["submit"](ws)
                checks["tool_created_delivery"] = (ws/"delivery/new.txt").read_bytes() == b"fixture"
                report = ws/"delivery/report.txt"
                report.write_text("submitted",encoding="ascii")
                checks.update(delivery_write_read=report.read_text(encoding="ascii")=="submitted",
                              parent_read_denied=inaccessible(lambda: (base/arm/"operator.txt").read_bytes()),
                              parent_listing_denied=inaccessible(lambda: list((base/arm).iterdir())),
                              sibling_read_denied=inaccessible(lambda: (base/other/"workspace/TASK.md").read_bytes()))
            finally:
                security.RevertToSelf()
                restricted.Close()
            assert all(checks.values()), checks
            results[arm] = checks
        token.Close()
        return results


if __name__ == "__main__":
    print(json.dumps(exercise(),indent=2))



