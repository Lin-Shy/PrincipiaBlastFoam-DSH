"""Trusted small dense linear solve for the public rectangular duct task."""
import json
import math


def solve(matrix, rhs):
    a = [list(row)+[float(v)] for row,v in zip(matrix,rhs)]
    n = len(a)
    for k in range(n):
        pivot = max(range(k,n),key=lambda i:abs(a[i][k]))
        a[k],a[pivot] = a[pivot],a[k]
        if a[k][k] == 0:
            raise ValueError("singular matrix")
        for i in range(k+1,n):
            factor = a[i][k]/a[k][k]
            for j in range(k+1,n+1):
                a[i][j] -= factor*a[k][j]
    x = [0.0]*n
    for i in reversed(range(n)):
        x[i] = (a[i][-1]-sum(a[i][j]*x[j] for j in range(i+1,n)))/a[i][i]
    if not all(map(math.isfinite,x)):
        raise ValueError("non-finite solution")
    return x


if __name__=="__main__":
    with open("payload/case.json") as inp:
        case = json.load(inp)
    x = solve(case["matrix"],case["rhs"])
    nx,ny = case["nx"],case["ny"]
    field = [[0.0]*(nx+1) for _ in range(ny+1)]
    for j in range(1,ny):
        for i in range(1,nx):
            field[j][i] = x[(j-1)*(nx-1)+i-1]
    with open("field.json","w") as out:
        json.dump(field,out,separators=(",",":"),allow_nan=False)
