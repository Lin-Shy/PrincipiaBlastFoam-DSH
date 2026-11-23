"""Fixed compute-node linear solver. The submitted project supplies all coefficients."""
import csv
import json
import math


def solve(rows):
    c = []
    d = []
    for radius, lower, diagonal, upper, rhs in rows:
        pivot = diagonal - lower * (c[-1] if c else 0)
        c.append(upper / pivot)
        d.append((rhs - lower * (d[-1] if d else 0)) / pivot)
    for j in range(len(d) - 2, -1, -1):
        d[j] -= c[j] * d[j+1]
    if not all(map(math.isfinite, d)):
        raise ValueError("non-finite velocity")
    return d


if __name__ == "__main__":
    with open("payload/case.json") as source:
        rows = json.load(source)["rows"]
    with open("profile.csv", "w") as stream:
        out = csv.writer(stream)
        out.writerow(["r_m", "u_m_s"])
        out.writerows((row[0], u) for row, u in zip(rows, solve(rows)))
