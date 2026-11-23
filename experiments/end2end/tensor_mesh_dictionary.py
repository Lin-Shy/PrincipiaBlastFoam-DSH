"""Compile a narrow Cartesian specification to input text; never generate a mesh.

Native OpenFOAM 9 multi-grading, one section per prescribed interval.
Not a general geometry classifier or a replacement for native acceptance tests.
"""
import math
import re


def compile_dictionary(axes, *, geometry, obstacles, patch):
    if geometry != "cartesian_box" or obstacles != []:
        raise ValueError("unsupported or unresolved geometry")
    if not isinstance(patch, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", patch):
        raise ValueError("one explicit exterior patch name required")
    if len(axes) != 3:
        raise ValueError("three axes required")
    for axis in axes:
        if len(axis) < 2 or any(not math.isfinite(v) for v in axis):
            raise ValueError("finite axis with at least two coordinates required")
        if any(b <= a for a, b in zip(axis, axis[1:])):
            raise ValueError("strictly increasing coordinates required")
    corners = ((0,0,0),(1,0,0),(1,1,0),(0,1,0),
               (0,0,1),(1,0,1),(1,1,1),(0,1,1))
    def fmt(v):
        return format(v, ".17g")
    vertices = ["(" + " ".join(fmt(axes[d][-1 if c[d] else 0]) for d in range(3)) + ")" for c in corners]
    grading = ["(" + " ".join(f"({fmt(b-a)} 1 1)" for a,b in zip(axis, axis[1:])) + ")" for axis in axes]
    return (
        "FoamFile { version 2.0; format ascii; class dictionary; object blockMeshDict; }\n"
        "convertToMeters 1;\nvertices\n(\n" + "\n".join(vertices) + "\n);\nblocks\n(\n"
        "hex (0 1 2 3 4 5 6 7) (" + " ".join(str(len(a)-1) for a in axes) + ")\n"
        "simpleGrading (\n" + "\n".join(grading) + "\n)\n);\nedges ();\n"
        "boundary (\n" + patch + " { type patch; faces (\n"
        "(0 4 7 3) (1 2 6 5) (0 1 5 4) (3 7 6 2) (0 3 2 1) (4 5 6 7)\n"
        "); }\n);\nmergePatchPairs ();\n"
    )
