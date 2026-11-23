"""Replay the frozen observer, export and independently compare every CSV value."""
import csv
import json
import subprocess
import sys
from decimal import Decimal
from pathlib import Path
from export_delivery import export

here = Path(__file__).resolve().parent
workspace = here.parents[3]
archive = workspace/"graduation-experiment-results/chapter3_end_to_end_evaluation/dsh"
frozen = archive/"pilot_decision_20261117/pair_final"
evidence = workspace/"graduation-datasets/chapter03_simulation_tasks/benchmark/case_reviews/Fouchier2020-Ground-RP80/job-8953576/collection-pyxz4uv3/evidence"
raw = evidence/"case/postProcessing/groundPressure/0/p"
task = frozen/"public_task/conditions.json"
out = Path(sys.argv[1])
out.mkdir(parents=True,exist_ok=False)
subprocess.run([sys.executable,"-B",str(frozen/"professional/workspace/domain/observe.py"),str(raw),
                "--ambient-pa","100000","--start","0","--end","0.003","--output",str(out/"before.json")],check=True)
export(raw,task,evidence/"run.json",out/"after")
native = [line.split() for line in raw.read_text().splitlines() if line.strip() and not line.startswith("#")]
with (out/"after/pressure.csv").open(newline="") as stream:
    reader = csv.DictReader(stream)
    for source, target in zip(native,reader,strict=True):
        assert Decimal(source[0]) == Decimal(target["time_s"])
        for index in range(1,4):
            p = Decimal(source[index])
            assert Decimal(target[f"P{index}_absolute_pa"]) == p
            assert Decimal(target[f"P{index}_overpressure_pa"]) == p-100000
review = here.parent/"review_delivery.py"
subprocess.run([sys.executable,"-B",str(review),"--task",str(task.parent),"--delivery",str(out/"after"),
                "--output",str(out/"external_review.json")],check=True)
old = json.loads((out/"before.json").read_text())
new = json.loads((out/"external_review.json").read_text())
assert new["raw_window_complete"] and [r["metrics"] for r in new["raw_recomputed_metrics"]] == old["metrics"]
print(f"{len(native)} timestamps; {3*len(native)} absolute and {3*len(native)} derived pressures checked; all three original metric sets reproduced.")
