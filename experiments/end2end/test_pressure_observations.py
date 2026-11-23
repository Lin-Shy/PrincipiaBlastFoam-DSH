import importlib.util
from pathlib import Path
import pytest

spec = importlib.util.spec_from_file_location("observations", Path(__file__).with_name("pressure_observations.py"))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def test_positive_area_clips_crossing_not_whole_trapezoid():
    value = m.metrics([(0., -1.), (2., 1.)], ambient_pa=0, pressure_unit="Pa")[0]
    assert value["whole_window_positive_area_pa_s"] == .5


def test_window_requires_coverage_and_interpolates_boundaries():
    rows = [(0., 0.), (1., 2.), (2., 0.)]
    assert m.window(rows, .5, 1.5) == [(.5, 1.), (1., 2.), (1.5, 1.)]
    with pytest.raises(ValueError, match="not covered"):
        m.window(rows, 0, 3)
    with pytest.raises(ValueError, match="pressure"):
        m.metrics(rows, ambient_pa=0, pressure_unit="m2/s2")


@pytest.mark.parametrize("text", ["0 1\n0 2\n", "0 1\n1 nan\n", "0 1\n1 2 3\n"])
def test_rejects_restart_nonfinite_and_column_mismatch(tmp_path, text):
    p = tmp_path / "p"
    p.write_text(text)
    with pytest.raises(ValueError):
        m.read_scalar_probes(p)


def test_retaining_peak_does_not_guarantee_integral_accuracy():
    rows = [(i/100, 10. if i == 51 else 0.) for i in range(101)]
    short = m.bounded_rows(rows, 8, preserve_peaks=True)
    full_metric = m.metrics(rows, ambient_pa=0, pressure_unit="Pa")[0]
    short_metric = m.metrics(short, ambient_pa=0, pressure_unit="Pa")[0]
    assert len(short) == 8
    assert short_metric["peak_overpressure_pa"] == full_metric["peak_overpressure_pa"]
    assert short_metric["whole_window_positive_area_pa_s"] > 2*full_metric["whole_window_positive_area_pa_s"]
