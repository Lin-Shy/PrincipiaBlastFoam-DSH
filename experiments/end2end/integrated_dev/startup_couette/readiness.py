"""Operator-only startup-Couette readiness using the frozen OpenFOAM bridge.

The target fixture and recovered fields are never public agent inputs.
"""
import json
from pathlib import Path
import shutil
import sys
import time

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent.parent))
import cluster_job
from pipe_flow.accounting_status import status

WS = HERE.parents[4]
BASE = WS / "graduation-experiment-results/chapter3_end_to_end_evaluation/dsh"
OUT = BASE / "cross_family_preparation_20261122/operator-readiness"
REFERENCE = BASE / "openfoam_cavity_solve_20261122_r2"
RID = "c3-startup-couette-readiness-20261122"


def put(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="ascii", newline="\n")


def header(name, kind="dictionary"):
    return "FoamFile { version 2.0; format ascii; class " + kind + "; object " + name + "; }\n"


def prepare():
    OUT.mkdir(exist_ok=False)
    payload = OUT / "payload"
    shutil.copytree(REFERENCE / "payload/case", payload / "case")
    shutil.copyfile(REFERENCE / "payload/run_case.sh", payload / "run_case.sh")
    case = payload / "case"
    put(case / "system/blockMeshDict", header("blockMeshDict") + """
convertToMeters 1;
vertices ((0 0 0)(0.05 0 0)(0.05 0.1 0)(0 0.1 0)(0 0 0.01)(0.05 0 0.01)(0.05 0.1 0.01)(0 0.1 0.01));
blocks (hex (0 1 2 3 4 5 6 7) (2 64 1) simpleGrading (1 1 1));
edges ();
boundary (
 lowerWall {type wall; faces ((0 1 5 4));}
 upperWall {type wall; faces ((3 7 6 2));}
 xMin {type cyclic; neighbourPatch xMax; faces ((0 4 7 3));}
 xMax {type cyclic; neighbourPatch xMin; faces ((1 2 6 5));}
 frontAndBack {type empty; faces ((0 3 2 1)(4 5 6 7));}
);
mergePatchPairs ();
""")
    put(case / "0/U", header("U", "volVectorField") + """
dimensions [0 1 -1 0 0 0 0]; internalField uniform (0 0 0);
boundaryField {
 lowerWall {type fixedValue; value uniform (0 0 0);}
 upperWall {type fixedValue; value uniform (0.2 0 0);}
 xMin {type cyclic;} xMax {type cyclic;} frontAndBack {type empty;}
}
""")
    put(case / "0/p", header("p", "volScalarField") + """
dimensions [0 2 -2 0 0 0 0]; internalField uniform 0;
boundaryField {
 lowerWall {type zeroGradient;} upperWall {type zeroGradient;}
 xMin {type cyclic;} xMax {type cyclic;} frontAndBack {type empty;}
}
""")
    put(case / "system/controlDict", header("controlDict") +
        "application icoFoam; startFrom startTime; startTime 0; stopAt endTime; endTime 0.1; deltaT 0.001; writeControl timeStep; writeInterval 50; writeFormat ascii; writePrecision 12; runTimeModifiable false;\n")
    put(case / "system/fvSolution", header("fvSolution") +
        "solvers { p {solver PCG; preconditioner DIC; tolerance 1e-9; relTol 0;} pFinal { $p; relTol 0;} U {solver smoothSolver; smoother symGaussSeidel; tolerance 1e-10; relTol 0;} } PISO {nCorrectors 2; nNonOrthogonalCorrectors 0; pRefCell 0; pRefValue 0;}\n")
    cluster_job.write(OUT / "plan.json", dict(task="startup Couette readiness", role="operator only; no agent score",
        parameters=dict(length_x=0.05, height=0.1, thickness=0.01, mesh=[2,64,1],
            upper_velocity=0.2, lower_velocity=0, nu=0.01, dt=0.001, end=0.1, write_interval=50),
        model_requests=0, node_jobs_limit=1, node_minutes=5, memory_mib=1024,
        run_id=RID, solver_sha256=json.loads((REFERENCE / "verified.json").read_bytes())["solver_sha256"],
        frozen_pipeline_sha256=cluster_job.digest(payload / "run_case.sh"),
        design_sha256=cluster_job.digest(WS / "graduation-thesis-materials/graduation-research/chapters/chapter03.md"),
        storage_preflight_sha256=cluster_job.digest(OUT.parent / "storage_preflight.json"),
        source_sha256=cluster_job.digest(Path(__file__)),
        files={str(path.relative_to(payload)): cluster_job.digest(path) for path in payload.rglob("*") if path.is_file()}))
    print("Prepared operator-only fixture; no remote mutation")


def execute():
    plan = json.loads((OUT / "plan.json").read_bytes())
    assert plan["source_sha256"] == cluster_job.digest(Path(__file__))
    payload = OUT / "payload"
    assert all(cluster_job.digest(payload / name) == value for name, value in plan["files"].items())
    config = json.loads((BASE / "pilot_decision_20261117/acceptance.config.json").read_bytes())
    config.update(tasks=1, memory_mib=1024, wall_minutes=5)
    grant = dict(live_actions_allowed=True, actions=["stage", "submit", "status", "collect"],
        run_ids=[RID], limits={key: config[key] for key in ("tasks", "memory_mib", "wall_minutes")})
    state = OUT / "operator"
    cluster_job.run("stage", config, RID, state, payload, grant)
    receipt = cluster_job.run("submit", config, RID, state, grant=grant)
    print(receipt["job_id"], flush=True)
    for _ in range(150):
        terminal = status(config, RID, receipt)
        if terminal["JobState"] not in ("PENDING", "RUNNING", "CONFIGURING", "COMPLETING"):
            cluster_job.write(OUT / "terminal.json", terminal)
            break
        time.sleep(4)
    else:
        raise TimeoutError("Owned job remains active; query the recorded ID, never resubmit")
    cluster_job.run("collect", config, RID, state, grant=grant)


if __name__ == "__main__":
    {"prepare": prepare, "execute": execute}[sys.argv[1]]()
