import importlib.util
import json
from pathlib import Path

import pytest

from admission import candidate


def load_function(file,name):
    spec = importlib.util.spec_from_file_location(file.stem,file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return getattr(module,name)


BASE = Path(__file__).resolve().parent.parent
validate = load_function(BASE/"pipe_flow/pipe_client.py","validate")
check_direction = load_function(BASE/"pipe_flow_v2/pipe_preflight.py","check_direction")


@pytest.mark.parametrize("row_sign",[1,-1])
def test_operator_checks_raw_candidate_in_either_sign_convention(row_sign):
    rows = [[i*.01/64,-row_sign,2*row_sign,-row_sign,-row_sign] for i in range(65)]
    with pytest.raises(ValueError,match="forcing orientation"):
        candidate(json.dumps({"rows":rows}).encode(),validate,check_direction)
    for row in rows:
        row[-1] *= -1
    raw = json.dumps({"rows":rows}).encode()
    accepted = candidate(raw,validate,check_direction)
    rows[1][-1] = 0
    assert accepted["rows"][1][-1] == row_sign
