"""Offline candidate: explicit pressure/window semantics before bounded presentation.

No solver, model, reference-answer loading, or task-success decisions. The positive
area is over the entire requested window, NOT a first-positive-phase impulse.
"""
from bisect import bisect_left
import math


def read_scalar_probes(path):
    rows = []
    width = None
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            row = tuple(float(x) for x in line.split())
            width = width or len(row)
            if len(row) != width or width < 2 or not all(math.isfinite(x) for x in row):
                raise ValueError("Malformed or nonfinite scalar probe data")
            if rows and row[0] <= rows[-1][0]:
                raise ValueError("Non-increasing time; resolve restart provenance explicitly")
            rows.append(row)
    if len(rows) < 2:
        raise ValueError("Insufficient pressure samples")
    return rows


def window(rows, start, end):
    if not math.isfinite(start) or not math.isfinite(end) or start >= end:
        raise ValueError("Invalid window")
    if rows[0][0] > start or rows[-1][0] < end:
        raise ValueError("Requested time window not covered; no extrapolation")
    times = [r[0] for r in rows]
    def boundary(t):
        i = bisect_left(times, t)
        if times[i] == t:
            return rows[i]
        a, b = rows[i-1], rows[i]
        weight = (t-a[0])/(b[0]-a[0])
        return (t, *(x+weight*(y-x) for x, y in zip(a[1:], b[1:])))
    return [boundary(start), *(r for r in rows if start < r[0] < end), boundary(end)]


def metrics(rows, *, ambient_pa, pressure_unit):
    if pressure_unit != "Pa" or not math.isfinite(ambient_pa):
        raise ValueError("Absolute pressure in Pa and explicit ambient pressure required")
    output = []
    for column in range(1, len(rows[0])):
        peak_index = max(range(len(rows)), key=lambda i: rows[i][column])
        pieces = []
        for a, b in zip(rows, rows[1:]):
            x, y = a[column]-ambient_pa, b[column]-ambient_pa
            dt = b[0]-a[0]
            if x >= 0 and y >= 0:
                pieces.append(.5*(x+y)*dt)
            elif x > 0:
                pieces.append(.5*x*dt*x/(x-y))
            elif y > 0:
                pieces.append(.5*y*dt*y/(y-x))
        output.append({"probe_column": column-1,
                       "peak_overpressure_pa": rows[peak_index][column]-ambient_pa,
                       "sampled_peak_time_s": rows[peak_index][0],
                       "whole_window_positive_area_pa_s": math.fsum(pieces)})
    return output


def bounded_rows(rows, budget, *, preserve_peaks=False):
    if budget < len(rows[0])+2:
        raise ValueError("Budget insufficient for endpoints and channel peaks")
    if budget >= len(rows):
        return rows[:]
    selected = {0, len(rows)-1}
    if preserve_peaks:
        selected.update(max(range(len(rows)), key=lambda i: rows[i][j]) for j in range(1, len(rows[0])))
    # Fill equally spaced ranks from the remaining rows, preserving exact budget.
    available = [i for i in range(len(rows)) if i not in selected]
    count = budget-len(selected)
    if count == 1:
        selected.add(available[len(available)//2])
    else:
        selected.update(available[round(k*(len(available)-1)/(count-1))] for k in range(count))
    return [rows[i] for i in sorted(selected)]
