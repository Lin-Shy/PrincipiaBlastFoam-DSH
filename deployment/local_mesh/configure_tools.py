"""Configure only blockMesh/checkMesh wrappers for the pinned local tool environment."""
from pathlib import Path
import hashlib
import json
import shlex

def main():
    app = Path(__file__).resolve().parents[2]
    workspace = app.parents[1]
    prefix = workspace/"runtime/openfoam"
    packages = [json.loads(p.read_text()) for p in (prefix/"conda-meta").glob("openfoam-*.json")]
    if len(packages) != 1 or (packages[0]["version"], packages[0]["build"]) != ("2412", "h946d6a9_1"):
        raise RuntimeError("Install pinned conda-forge openfoam=2412=h946d6a9_1 first")
    wrappers = workspace/"runtime/mesh-bin"
    wrappers.mkdir(exist_ok=True)
    for tool in ("blockMesh", "checkMesh"):
        binary = prefix/"bin"/tool
        if not binary.is_file():
            raise RuntimeError("Missing "+tool)
        script = ("#!/bin/bash\nset -e\nexport CONDA_PREFIX="+shlex.quote(str(prefix))+"\n"
                  '. "$CONDA_PREFIX/etc/conda/activate.d/openfoam_activate.sh"\n'
                  'export LD_LIBRARY_PATH="$CONDA_PREFIX/lib' + '$' + '{LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"\n'
                  'exec "$CONDA_PREFIX/bin/'+tool+'" "$@"\n')
        (wrappers/tool).write_text(script)
        (wrappers/tool).chmod(0o755)
    identity = {"distribution":"conda-forge OpenCFD OpenFOAM", "version":packages[0]["version"],
                "build":packages[0]["build"], "prefix":str(prefix),
                "package_sha256":packages[0].get("sha256"),
                "binaries":{name:hashlib.sha256((prefix/"bin"/name).read_bytes()).hexdigest()
                            for name in ("blockMesh","checkMesh")},
                "scope":"local lightweight mesh only; HPC Foundation 9 compatibility not asserted"}
    (workspace/"runtime/local-mesh-identity.json").write_text(json.dumps(identity,indent=2))
    print(json.dumps(identity))
if __name__ == "__main__":
    main()
