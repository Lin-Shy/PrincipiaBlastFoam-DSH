# Linux lightweight mesh tools

The dedicated MCP tool `mesh_case(case_path, operation)` supports `blockMesh` and `checkMesh` on the independent Linux host. It does not call Allrun or a solver. Case paths use the normal PRINCIPIA_CASE_ROOT validation. Full run_case and complete_workflow(require_execution=True) remain HPC-only; ENABLE_EXECUTION=false stays in the Web profile.

## Installation and entry

Use an isolated conda prefix, not the controller Python environment:

```sh
CONDA_PKGS_DIRS="$DSH_WORKSPACE/runtime/conda-cache" /data/miniconda3/bin/conda create --prefix "$DSH_WORKSPACE/runtime/openfoam" -c conda-forge --override-channels openfoam=2412=h946d6a9_1 -y
python deployment/local_mesh/configure_tools.py
export PRINCIPIA_LOCAL_MESH_ENABLED=true
export PRINCIPIA_LOCAL_MESH_BIN="$DSH_WORKSPACE/runtime/mesh-bin"
export PATH="$PRINCIPIA_LOCAL_MESH_BIN:$PATH"
```

The current environment.sh already contains these exports; serve_web.py also passes the two mesh settings to MCP explicitly. configure_tools.py checks the package build, creates only blockMesh/checkMesh wrappers, and writes runtime/local-mesh-identity.json with hashes. Package source: [conda-forge OpenFOAM](https://github.com/conda-forge/openfoam-feedstock).

## Current supported scope

Conservative deployment defaults: at most 100,000 explicit hex cells, one CPU, 1 GiB address space, 30 seconds, 128 MiB temporary output and 32 MiB input. These are operational bounds, not a research definition of lightweight computation. Large, unsupported or resource-constrained tasks receive an explicit error directing them to HPC; no automatic submission or host fallback occurs.

Input is ASCII, contains no dynamic code/includes/libraries or external geometry, and uses no symlinks. blockMesh uses explicit cell counts; checkMesh reads the existing polyMesh. Temporary cases receive minimal static controlDict/fvSchemes/fvSolution; case-provided functions are not loaded. Existing meshes are not overwritten. Logs, input/output hashes, location and return codes go to local-mesh-evidence. Success of checkMesh requires both exit 0 and Mesh OK.

This is bounded tool routing, not an OS sandbox: the account and DSH shell retain their existing permissions. The isolated OpenFOAM distribution includes other executables, but they are not exposed through mesh-bin or this MCP tool.

## Verified 2026-11-23

Real MCP calls created a 1,000-cell cube in 0.305 seconds and checked it in 0.104 seconds (both exit 0; Mesh OK). A billion-cell input and full solver invocation were rejected. 41 related tests passed. Web was restarted and authenticated HTTP access returned 200; the model ledger stayed at three requests. No new model call, solver or HPC job was launched.

OpenCFD 2412 is the local mesher. The earlier HPC acceptance used Foundation 9; cross-distribution mesh transfer/solver compatibility is not established by this test. Formal workflows must pin compatible versions or regenerate the mesh on HPC. Evidence: workspace/maintenance/local-mesh-acceptance-20261123. This is maintenance acceptance, not batch or comparative research evidence.
