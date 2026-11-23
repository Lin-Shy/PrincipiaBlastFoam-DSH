"""Public starter: constant-viscosity shear between two flat plates."""
import json
from pathlib import Path


def assemble(gap_m, lower_m_s, upper_m_s, intervals):
    spacing = gap_m/intervals
    rows = [[0.0,0.0,1.0,0.0,lower_m_s]]
    for i in range(1,intervals):
        rows.append([i*spacing,-1.0,2.0,-1.0,0.0])
    rows.append([gap_m,0.0,1.0,0.0,upper_m_s])
    return {"rows":rows}


if __name__ == "__main__":
    initial = assemble(.01,0.0,.1,64)
    Path("case.json").write_text(json.dumps(initial,indent=2),encoding="ascii")
