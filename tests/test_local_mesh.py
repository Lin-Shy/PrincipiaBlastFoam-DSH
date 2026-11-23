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

def test_owner_cell_count():
    assert local_mesh._mesh_cells("FoamFile {} 3 (0 1 2)") == 3
    with pytest.raises(ValueError):
        local_mesh._mesh_cells("FoamFile {} 1 (1000000)")
