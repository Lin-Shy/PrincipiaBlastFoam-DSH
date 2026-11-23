"""Professional-only development verification after two exposed PIPE-01 pairs."""
import argparse
import json
from pathlib import Path
import shutil
import sys

SOURCE = Path(__file__).resolve().parent
sys.path.insert(0,str(SOURCE.parent/"pipe_flow_v2"))
import round2
from run_pair import base,read,sha,write
import run_pair
from admission import await_input

PAIR = base/"pipe_flow_admission_20261120"
ARM = "professional"
RID = "c3-pipe03-professional-20261120"


def prepare():
    round2.PAIR = PAIR
    round2.prepare()
    root = PAIR/ARM
    client = root/"workspace/common/pipe_client.py"
    shutil.copyfile(SOURCE/"pipe_client.py",client)
    skill = root/"skills/steady-pipe-delivery/SKILL.md"
    with skill.open("a",encoding="utf8") as out:
        out.write("\n沿轴线取 z 正方向，公开的压力下降率 G 表示 G = −dp/dz。"
                  "由 0 = −dp/dz + μ/r·d(r·du/dr)/dr 可知，用正主对角表示负扩散时，"
                  "右端驱动为 −dp/dz。先核对整个离散行的符号；给方程两侧同时乘 −1 不改变解。"
                  "操作者从实际登记的矩阵独立核验。修订应来自受测工程的源码，"
                  "请按公开客户端返回的原件与回执复跑和封存。\n")
    path = PAIR/"manifest.json"
    m = read(path)
    for p in [client,skill,*SOURCE.glob("*.py")]:
        m["source_sha256"][str(p)] = sha(p)
    m.update(role="professional_only_development_verification",live_arms=[ARM],
             comparison="round 2 general retained as historical development comparator",
             changes=["trusted operator admission on actual immutable rows","client feedback","pressure-gradient convention in skill"])
    path.write_text(json.dumps(m,indent=2,ensure_ascii=False),encoding="utf8")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("action",choices=("prepare","agent","operator","reconcile","check"))
    action = p.parse_args().action
    run_pair.PAIR = PAIR
    if action=="prepare":
        return prepare()
    if action=="agent":
        return run_pair.run(ARM)
    if action=="check":
        from check_delivery import verify
        review = verify(ARM)
        print(json.dumps(review,indent=2))
        return 0 if review["numerical_checks_passed"] and review["delivered_matrix_matches_staged"] else 1
    if action=="reconcile":
        from reconcile import recover
        return recover(ARM,pair=PAIR,run_id=RID)
    from operate import operate
    from pipe_client import validate
    from pipe_preflight import check_direction
    root = PAIR/ARM
    pins = read(PAIR/"manifest.json")["source_sha256"]
    for source in [SOURCE/"admission.py",SOURCE/"round3.py",SOURCE.parent/"pipe_flow_v2/pipe_preflight.py"]:
        if sha(source)!=pins[str(source)]:
            raise ValueError("operator admission source changed")
    if (root/"operator/job_receipt.json").exists():
        return operate(ARM,pair=PAIR,run_id=RID,collect_only=True)
    accepted = await_input(root,validate,check_direction,write)
    if accepted is not None:
        return operate(ARM,pair=PAIR,run_id=RID,accepted_case=accepted)


if __name__=="__main__":
    sys.exit(main())
