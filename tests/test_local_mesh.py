from pathlib import Path
import json
import os
import pytest
from principia_core import local_mesh

DICT = """FoamFile { version 2.0; format ascii; class dictionary; object blockMeshDict; }
convertToMeters 1;
vertices ((0 0 0)(1 0 0)(1 1 0)(0 1 0)(0 0 1)(1 0 1)(1 1 1)(0 1 1));
blocks (hex (0 1 2 3 4 5 6 7) (10 10 10) simpleGrading (1 1 1));
edges ();
boundary (walls {type wall; faces ((0 3 2 1)(4 5 6 7)(0 1 5 4)(1 2 6 5)(2 3 7 6)(3 0 4 7));});
mergePatchPairs ();
"""

def test_cell_budget_and_unknown_size_rejected():
    assert local_mesh.estimate_cells(DICT) == 1000
    with pytest.raises(ValueError, match="HPC"):
        local_mesh.estimate_cells(DICT.replace("(10 10 10)", "(1000 1000 1000)"))
    with pytest.raises(ValueError):
        local_mesh.estimate_cells(DICT.replace("(10 10 10)", "($nx 10 10)"))

@pytest.mark.parametrize("suffix", ['#include "/etc/passwd"', "libs (evil);", "functions {}", "type codedFixedValue;", "geometry {}"])
def test_dynamic_or_external_input_rejected(suffix):
    with pytest.raises(ValueError):
        local_mesh.estimate_cells(DICT + suffix)

def test_solver_is_not_an_operation(tmp_path):
    with pytest.raises(ValueError, match="solvers use HPC"):
        local_mesh.run_local_mesh(tmp_path, "icoFoam")

def test_disabled_separate_from_full_execution_flag(tmp_path, monkeypatch):
    monkeypatch.setenv("ENABLE_EXECUTION", "true")
    monkeypatch.setenv("PRINCIPIA_LOCAL_MESH_ENABLED", "false")
    with pytest.raises(ValueError, match="disabled"):
        local_mesh.run_local_mesh(tmp_path, "blockMesh")

def test_symlink_and_binary_inputs_rejected(tmp_path):
    outside = tmp_path/"outside"; outside.write_text(DICT)
    case = tmp_path/"case"; case.mkdir()
    link = case/"blockMeshDict"; link.symlink_to(outside)
    with pytest.raises(ValueError, match="Symlink"):
        local_mesh._input(link, case)
    link.unlink(); link.write_text(DICT.replace("format ascii", "format binary"))
    with pytest.raises(ValueError, match="ASCII"):
        local_mesh._input(link, case)

def test_existing_mesh_is_never_overwritten(tmp_path, monkeypatch):
    tools = tmp_path/"bin"; tools.mkdir()
    for name in ("blockMesh", "checkMesh"):
        f=tools/name; f.write_text("#!/bin/sh\nexit 99\n"); f.chmod(0o700)
    monkeypatch.setenv("PRINCIPIA_LOCAL_MESH_BIN", str(tools))
    monkeypatch.setenv("PRINCIPIA_LOCAL_MESH_ENABLED", "true")
    (tmp_path/"system").mkdir(); (tmp_path/"system/blockMeshDict").write_text(DICT)
    (tmp_path/"constant/polyMesh").mkdir(parents=True)
    with pytest.raises(ValueError, match="not overwritten"):
        local_mesh.run_local_mesh(tmp_path, "blockMesh")

def test_wall_timeout_terminates_child_without_publishing(tmp_path, monkeypatch):
    tools=tmp_path/"bin"; tools.mkdir()
    for name in ("blockMesh","checkMesh"):
        f=tools/name; f.write_text("#!/bin/sh\nsleep 10\n"); f.chmod(0o700)
    monkeypatch.setenv("PRINCIPIA_LOCAL_MESH_BIN", str(tools))
    monkeypatch.setenv("PRINCIPIA_LOCAL_MESH_ENABLED", "true")
    monkeypatch.setattr(local_mesh,"MAX_SECONDS",1)
    (tmp_path/"system").mkdir(); (tmp_path/"system/blockMeshDict").write_text(DICT)
    result=local_mesh.run_local_mesh(tmp_path,"blockMesh")
    assert result["passed"] is False
    assert result["failure"] == "local time/output limit exceeded"
    assert result["elapsed_seconds"] < 3
    assert not (tmp_path/"constant/polyMesh").exists()
    assert not list(tmp_path.glob(".local-mesh-*"))
