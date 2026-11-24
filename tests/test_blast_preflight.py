from pathlib import Path
from principia_core.blast_preflight import preflight_blast_case


def _make_valid_blast_case(case: Path, *, max_co: float = 0.25, nsub: int = 4) -> Path:
    (case / "system").mkdir(parents=True)
    (case / "constant").mkdir(parents=True)
    (case / "0").mkdir(parents=True)
    (case / "system" / "controlDict").write_text(
        f"""FoamFile {{ version 2.0; format ascii; class dictionary; object controlDict; }}
application blastFoam;
startTime 0;
endTime 0.01;
deltaT 1e-6;
adjustTimeStep yes;
maxCo {max_co};
functions
{{
    probes1
    {{
        type probes;
        probeLocations ((1 0 0));
    }}
}}
""",
        encoding="utf-8",
    )
    (case / "system" / "fvSchemes").write_text("ddtSchemes { default Euler; }\n", encoding="utf-8")
    (case / "system" / "fvSolution").write_text("solvers {}\n", encoding="utf-8")
    (case / "system" / "blockMeshDict").write_text(
        """vertices
(
    (0 0 0) (2 0 0) (2 2 0) (0 2 0)
    (0 0 2) (2 0 2) (2 2 2) (0 2 2)
);
blocks
(
    hex (0 1 2 3 4 5 6 7) (20 20 20) simpleGrading (1 1 1)
);
boundary
(
    walls { type wall; faces ((0 4 7 3)); }
    outlet { type patch; faces ((1 2 6 5)); }
);
""",
        encoding="utf-8",
    )
    (case / "system" / "setFieldsDict").write_text(
        """regions
(
    sphereToCell
    {
        centre (1 1 1);
        radius 0.2;
    }
);
""",
        encoding="utf-8",
    )
    (case / "system" / "decomposeParDict").write_text(
        f"""numberOfSubdomains {nsub};
method simple;
simpleCoeffs
{{
    n (2 2 1);
}}
""",
        encoding="utf-8",
    )
    (case / "constant" / "phaseProperties").write_text(
        """c4
{
    equationOfState JWL;
    activationModel linear;
    detonationPoints ( (1 1 1) );
    rho0 1601;
    e0 8.7e9;
    A 6.09e11;
    B 1.29e10;
    R1 4.5;
    R2 1.4;
    omega 0.25;
}
""",
        encoding="utf-8",
    )
    for field in ("p", "U"):
        (case / "0" / field).write_text(
            """boundaryField
{
    walls { type zeroGradient; }
    outlet { type waveTransmissive; }
}
""",
            encoding="utf-8",
        )
    return case


def test_preflight_valid_blast_case(tmp_path):
    case = _make_valid_blast_case(tmp_path / "valid_blast")
    res = preflight_blast_case(case)
    assert res["ok"] is True
    assert res["solver"] == "blastFoam"
    assert res["errors"] == []
    assert any("cells/R" in w for w in res["warnings"])


def test_preflight_catches_detonation_outside_charge_and_patch_mismatch(tmp_path):
    case = _make_valid_blast_case(tmp_path / "bad_blast", max_co=0.9, nsub=8)
    (case / "constant" / "phaseProperties").write_text(
        """c4
{
    equationOfState JWL;
    detonationPoints ( (1.9 1 1) );
    rho0 1601;
    e0 8.7e9;
    A 6.09e11;
    B 1.29e10;
    R1 4.5;
    R2 1.4;
}
""",
        encoding="utf-8",
    )
    (case / "0" / "p").write_text("boundaryField\n{\n    walls { type zeroGradient; }\n}\n", encoding="utf-8")
    res = preflight_blast_case(case)
    assert res["ok"] is False
    joined = " | ".join(res["errors"])
    assert "omega" in joined
    assert "outside sphereToCell" in joined
    assert "numberOfSubdomains (8)" in joined
    assert "outlet" in joined
    assert any("maxCo=0.9" in w for w in res["warnings"])


def test_preflight_mcp_tool_registered(tmp_path, monkeypatch):
    import asyncio
    from mcp_servers.principia_domain.server import blast_preflight_check, mcp

    monkeypatch.setenv("PRINCIPIA_CASE_ROOT", str(tmp_path))
    case = _make_valid_blast_case(tmp_path / "mcp_case")
    res = blast_preflight_check(str(case))
    assert res["ok"] is True
    tools = {t.name for t in asyncio.run(mcp.list_tools())}
    assert "blast_preflight_check" in tools
    assert "pressure_probe_summary" in tools
