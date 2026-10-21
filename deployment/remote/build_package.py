"""Build a tiny deploy archive without agents, corpora, harness or experiment data."""
from pathlib import Path
import argparse
import tarfile

ROOT = Path(__file__).resolve().parents[2]
FILES = {
    "src/principia_core/__init__.py": "principia_core/__init__.py",
    "src/principia_core/remote_simulation.py": "principia_core/remote_simulation.py",
    "mcp_servers/__init__.py": "mcp_servers/__init__.py",
    "mcp_servers/simulation/__init__.py": "mcp_servers/simulation/__init__.py",
    "mcp_servers/simulation/server.py": "mcp_servers/simulation/server.py",
    "deployment/remote/run_case.sh": "run_case.sh",
    "deployment/remote/install.sh": "install.sh",
    "deployment/remote/simulation.env.example": "simulation.env.example",
    "deployment/remote/principia-simulation.service.example": "principia-simulation.service.example",
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / ".local/simulation-service.tar.gz")
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(args.output, "w:gz") as archive:
        for source, target in FILES.items():
            info = archive.gettarinfo(str(ROOT / source), arcname=target)
            info.mode = 0o755 if target.endswith(".sh") else 0o644
            with (ROOT / source).open("rb") as handle:
                archive.addfile(info, handle)
    print(f"{args.output.resolve()} ({args.output.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
