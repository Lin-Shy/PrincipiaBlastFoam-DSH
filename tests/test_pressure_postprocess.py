import pytest
from principia_core.pressure_postprocess import extract_pressure_summary


def _write_probe_fixture(case):
    probe_dir = case / "postProcessing" / "probes" / "0"
    probe_dir.mkdir(parents=True)
    probe_file = probe_dir / "p"
    rows = [
        "# Probe 0 (1.0 0.0 0.5)",
        "# Probe 1 (2.0 0.0 0.5)",
        "# Time  0  1",
        "0.0000 101325.0 101325.0",
        "0.0010 101325.0 101325.0",
        "0.0020 151325.0 101325.0",
        "0.0030 126325.0 121325.0",
        "0.0040 96325.0  111325.0",
        "0.0050 116325.0 100325.0",
        "0.0060 99325.0  105325.0",
    ]
    probe_file.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return probe_file


def test_extract_pressure_summary_landmarks_and_impulse(tmp_path):
    case = tmp_path / "case_ok"
    _write_probe_fixture(case)
    res = extract_pressure_summary(case)
    assert res["ok"] is True
    assert res["has_nonfinite"] is False
    assert len(res["probes"]) == 2
    p0 = res["probes"][0]
    assert p0["coords"] == (1.0, 0.0, 0.5)
    assert p0["p_over_max_pa"] == pytest.approx(50000.0)
    assert p0["t_peak_s"] == pytest.approx(0.002)
    assert p0["t_arrival_s"] == pytest.approx(0.002)
    assert p0["positive_duration_s"] > 0.001
    assert p0["i_pos_pa_s"] > 0.0
    assert p0["p_under_min_pa"] == pytest.approx(-5000.0)
    assert len(p0["secondary_peaks"]) == 1
    assert p0["secondary_peaks"][0]["t_s"] == pytest.approx(0.005)


def test_extract_pressure_summary_nonfinite_and_trend_reference(tmp_path):
    case = tmp_path / "case_ref"
    pf = _write_probe_fixture(case)
    pf.write_text(pf.read_text(encoding="utf-8") + "0.0070 NaN 101325.0\n", encoding="utf-8")
    ref = [
        {"t": 0.000, "p_over": 0.0},
        {"t": 0.002, "p_over": 48000.0},
        {"t": 0.003, "p_over": 24000.0},
        {"t": 0.004, "p_over": -4000.0},
    ]
    res = extract_pressure_summary(case, reference_points={"probe_0": ref})
    assert res["ok"] is True
    assert res["has_nonfinite"] is True
    cmp0 = res["probes"][0]["trend_comparison"]
    assert cmp0["valid"] is True
    assert cmp0["pearson_r"] > 0.99
    assert cmp0["arrival_delta_s"] == pytest.approx(0.0)
    assert "mape_percent" in cmp0["reference_metadata"]


def test_extract_pressure_rejects_traversal_and_mcp_wrapper(tmp_path, monkeypatch):
    from mcp_servers.principia_domain.server import pressure_probe_summary

    monkeypatch.setenv("PRINCIPIA_CASE_ROOT", str(tmp_path))
    case = tmp_path / "case_mcp"
    _write_probe_fixture(case)
    with pytest.raises(ValueError):
        extract_pressure_summary(case, probe_dir="../outside")
    out = pressure_probe_summary(str(case))
    assert out["ok"] is True
    assert len(out["probes"]) == 2
