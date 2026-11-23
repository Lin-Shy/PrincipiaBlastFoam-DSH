"""Allocated-node ordinary-fluid cavity mesh and initialization readiness."""
from pathlib import Path
import json,sys,time
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import cluster_job
from pipe_flow.accounting_status import status
WS=Path(__file__).resolve().parents[4]
OUT=WS/"graduation-experiment-results/chapter3_end_to_end_evaluation/dsh/openfoam_cavity_readiness_20261122_r2"
RID="c3-cavity-readiness-r2-20261122"
def put(p,text):
 p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text,encoding="ascii",newline="\n")
def header(obj,cls="dictionary"):
 return 'FoamFile { version 2.0; format ascii; class '+cls+'; object '+obj+'; }\n'
def main():
 OUT.mkdir(exist_ok=False)
 payload=OUT/"payload"
 case=payload/"case"
 put(case/"system/blockMeshDict",header("blockMeshDict")+"""
convertToMeters 1;
vertices ((0 0 0)(0.1 0 0)(0.1 0.1 0)(0 0.1 0)(0 0 0.01)(0.1 0 0.01)(0.1 0.1 0.01)(0 0.1 0.01));
blocks (hex (0 1 2 3 4 5 6 7) (20 20 1) simpleGrading (1 1 1));
edges ();
boundary (
 movingWall {type wall; faces ((3 7 6 2));}
 fixedWalls {type wall; faces ((0 4 7 3)(2 6 5 1)(1 5 4 0));}
 frontAndBack {type empty; faces ((0 3 2 1)(4 5 6 7));}
);
mergePatchPairs ();
""")
 put(case/"system/controlDict",header("controlDict")+"application icoFoam; startFrom startTime; startTime 0; stopAt endTime; endTime 0.5; deltaT 0.005; writeControl timeStep; writeInterval 20; writeFormat ascii; writePrecision 10; runTimeModifiable false;\n")
 put(case/"system/fvSchemes",header("fvSchemes")+"ddtSchemes {default Euler;} gradSchemes {default Gauss linear;} divSchemes {default none; div(phi,U) Gauss linear;} laplacianSchemes {default Gauss linear orthogonal;} interpolationSchemes {default linear;} snGradSchemes {default orthogonal;}\n")
 put(case/"system/fvSolution",header("fvSolution")+"solvers { p {solver PCG; preconditioner DIC; tolerance 1e-6; relTol 0;} U {solver smoothSolver; smoother symGaussSeidel; tolerance 1e-5; relTol 0;} } PISO {nCorrectors 2; nNonOrthogonalCorrectors 0; pRefCell 0; pRefValue 0;}\n")
 put(case/"constant/transportProperties",header("transportProperties")+"transportModel Newtonian; nu [0 2 -1 0 0 0 0] 0.01;\n")
 put(case/"0/U",header("U","volVectorField")+"dimensions [0 1 -1 0 0 0 0]; internalField uniform (0 0 0); boundaryField {movingWall {type fixedValue; value uniform (1 0 0);} fixedWalls {type fixedValue; value uniform (0 0 0);} frontAndBack {type empty;}}\n")
 put(case/"0/p",header("p","volScalarField")+"dimensions [0 2 -2 0 0 0 0]; internalField uniform 0; boundaryField {movingWall {type zeroGradient;} fixedWalls {type zeroGradient;} frontAndBack {type empty;}}\n")
 put(case/"system/setFieldsDict",header("setFieldsDict")+"defaultFieldValues (volVectorFieldValue U (0 0 0) volScalarFieldValue p 0); regions ();\n")
 put(payload/"run_case.sh",'''set -eu
mkdir -p case
cp -r payload/case/. case/
blockMesh -case case > logs/blockMesh.log 2>&1
checkMesh -case case > logs/checkMesh.log 2>&1
setFields -case case > logs/setFields.log 2>&1
printf 'mesh_and_initialization_complete\n' > readiness.txt
if command -v icoFoam > solver_path.txt; then
 icoFoam -case case > logs/icoFoam.log 2>&1
 printf 'solver_complete\n' >> readiness.txt
else
 printf 'solver_unavailable\n' >> readiness.txt
fi
sha256sum case/0/U case/0/p case/constant/polyMesh/* > field_hashes.txt
''')
 cfg=json.loads((OUT.parent/"pilot_decision_20261117/acceptance.config.json").read_bytes())
 cfg.update(tasks=1,memory_mib=1024,wall_minutes=5)
 grant=dict(live_actions_allowed=True,actions=["stage","submit","status","collect"],run_ids=[RID],limits={k:cfg[k] for k in ("tasks","memory_mib","wall_minutes")})
 cluster_job.write(OUT/"plan.json",dict(task="ordinary nonreacting lid-driven cavity",model_requests=0,node_jobs=1,minutes=5,cells=400,level="operator-engineered readiness; no agent capability score",solver_missing_at_preflight=True,files={str(p.relative_to(payload)):cluster_job.digest(p) for p in payload.rglob("*") if p.is_file()}))
 state=OUT/"operator"
 cluster_job.run("stage",cfg,RID,state,payload,grant)
 receipt=cluster_job.run("submit",cfg,RID,state,grant=grant)
 print(receipt["job_id"],flush=True)
 for _ in range(150):
  result=status(cfg,RID,receipt)
  if result["JobState"] not in ("PENDING","RUNNING","CONFIGURING","COMPLETING"):
   cluster_job.write(OUT/"terminal.json",result);break
  time.sleep(4)
 else: raise TimeoutError("owned job still active")
 cluster_job.run("collect",cfg,RID,state,grant=grant)
if __name__=="__main__":main()
