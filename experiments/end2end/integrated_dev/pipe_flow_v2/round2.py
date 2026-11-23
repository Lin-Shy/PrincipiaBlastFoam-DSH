"""Second PIPE-01 development pair; preserve the original task and first pair."""
import argparse
import json
from pathlib import Path
import shutil
import sys

SOURCE = Path(__file__).resolve().parent
sys.path.insert(0,str(SOURCE.parent/"pipe_flow"))
import run_pair
from run_pair import ARMS, base, read, sha

PAIR = base/"pipe_flow_round2_20261120"


def prepare():
    run_pair.PAIR = PAIR
    run_pair.prepare()
    manifest_path = PAIR/"manifest.json"
    manifest = read(manifest_path)
    pins = manifest["source_sha256"]
    for arm in ARMS:
        common = PAIR/arm/"workspace/common"
        shutil.copyfile(common/"pipe_client.py",common/"pipe_schema.py")
        shutil.copyfile(SOURCE/"pipe_client.py",common/"pipe_client.py")
        if arm == "professional":
            shutil.copyfile(SOURCE/"pipe_preflight.py",common/"pipe_preflight.py")
            skill = PAIR/arm/"skills/steady-pipe-delivery/SKILL.md"
            skill.parent.mkdir()
            shutil.copyfile(SOURCE/"SKILL.md",skill)
            pins[str(skill)] = sha(skill)
        for p in common.glob("*.py"):
            pins[str(p)] = sha(p)
    for p in SOURCE.glob("*.py"):
        pins[str(p)] = sha(p)
    pins[str(SOURCE/"SKILL.md")] = sha(SOURCE/"SKILL.md")
    manifest.update(role="development_retest_after_PIPE01_exposure",
                    changes=["cwd-independent common client with digest checks", "professional forcing orientation check and delivery skill"],
                    fixed="same public task, DSH profiles, model, node resources and request limit")
    manifest_path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action",choices=["prepare","agent","operator","reconcile","check"])
    parser.add_argument("arm",choices=ARMS,nargs="?")
    args = parser.parse_args()
    if args.action == "prepare":
        return prepare()
    if not args.arm:
        parser.error("arm required")
    run_pair.PAIR = PAIR
    if args.action == "agent":
        return run_pair.run(args.arm)
    rid = "c3-pipe02-"+args.arm+"-20261120"
    if args.action == "operator":
        from operate import operate
        return operate(args.arm, pair=PAIR, run_id=rid)
    if args.action == "reconcile":
        from reconcile import recover
        return recover(args.arm, pair=PAIR, run_id=rid)
    from check_delivery import verify
    result = verify(args.arm)
    print(json.dumps(result,indent=2))
    return 0 if result["numerical_checks_passed"] and result["delivered_matrix_matches_staged"] else 1


if __name__ == "__main__":
    sys.exit(main())
