"""Start the local chapter development profile; no network model or scheduler."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from prepare_system_comparison import WS, common_environment
from runtime_config import prepare, runtime_node
from measurement_profile import extend_profile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", choices=["general", "professional"])
    parser.add_argument("workdir", type=Path)
    parser.add_argument("action", choices=["catalog", "invoke", "accept", "delivery-check"])
    parser.add_argument("tool", nargs="?")
    parser.add_argument("--args-file", type=Path)
    parser.add_argument("--delivery-controls", action="store_true", help="Opt in to experimental manifest checks and repeated-shell guard")
    args = parser.parse_args()
    cwd = args.workdir.resolve()
    cwd.mkdir(parents=True, exist_ok=True)
    runtime = WS/".chapter3-runtime/stage-20261117/dsh"
    template = WS/"graduation-experiment-results/chapter3_end_to_end_evaluation/dsh/pilot_decision_20261117/pair_final/general"
    params = json.loads(args.args_file.read_text(encoding="utf-8-sig")) if args.args_file else {}
    # Windows ACL shell runner requires its temporary root outside the workspace.
    with tempfile.TemporaryDirectory(prefix=".c3-profile-",dir=cwd.parent) as temp:
        root = Path(temp)
        for folder in ["home","agents_home","skills","user","tmp","cache"]:
            (root/folder).mkdir()
        if args.profile == "professional":
            shutil.copytree(HERE/"engineering-delivery", root/"skills/engineering-delivery")
            shutil.copytree(WS/"PrincipiaBlastFoam-DSH/.dsh/skills/blastfoam-quality-review",root/"skills/blastfoam-quality-review")
        profile = (template/"dump.yml").read_text(encoding="utf-8").replace(str(template),str(root))
        if args.profile == "professional":
            profile += "\n- id: engineering-time-series\n  name: " + (HERE/"pressure-tool.mjs").as_uri() + "\n"
            profile = extend_profile(profile, root)
        if args.delivery_controls:
            profile += "\n- id: delivery-controls\n  name: " + (HERE/"delivery-controls.mjs").as_uri() + "\n"
        (root/"dump.yml").write_text(profile,encoding="utf-8")
        prepare(root,runtime)
        env = common_environment(root)
        env.update(C3_PYTHON=sys.executable,C3_MODULE_PATH=str(HERE.parent),C3_RUNTIME=str(runtime))
        cmd = [runtime_node(runtime),str(HERE/"driver.mjs"),str(runtime),str(root),args.profile,args.action,args.tool or "",json.dumps(params)]
        subprocess.run(cmd,cwd=cwd,env=env,check=True,timeout=300)


if __name__ == "__main__":
    main()
