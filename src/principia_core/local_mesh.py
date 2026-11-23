"""Conservative mesh-scale inspection shared by simulation_cli; no execution backend."""
from __future__ import annotations
import re
MAX_CELLS = 100_000

def _plain(text: str) -> str:
    text = re.sub(r"/\*.*?\*/|//[^\n]*", "", text, flags=re.S)
    if re.search(r"[#$]|\b(?:libs|functions|coded\w*|codeStream|systemCall|geometry)\b", text):
        raise ValueError("Local mesh input must not contain directives, dynamic code, libraries or external geometry")
    return text

def estimate_cells(text: str) -> int:
    text = _plain(text)
    blocks = re.findall(r"\bhex\s*\([^)]*\)\s*(?:[A-Za-z_]\w*\s*)?\(\s*(\d+)\s+(\d+)\s+(\d+)\s*\)", text)
    if not blocks or len(blocks) != len(re.findall(r"\bhex\b", text)):
        raise ValueError("Only explicit hex block cell counts are supported locally")
    total = 0
    for dims in blocks:
        x, y, z = map(int, dims)
        if min(x, y, z) < 1:
            raise ValueError("Mesh dimensions must be positive")
        total += x*y*z
    if total > MAX_CELLS:
        raise ValueError(f"Mesh has {total} cells; local cap is {MAX_CELLS}. Use the HPC workflow")
    return total

def _mesh_cells(owner: str, neighbour: str = "") -> int:
    text = _plain(owner)
    # The labelList payload follows the FoamFile dictionary.
    match = re.search(r"}\s*\d+\s*\((.*?)\)\s*;?\s*$", text, re.S)
    if not match or not re.fullmatch(r"[\d\s]*", match[1]):
        raise ValueError("Unsupported owner labelList")
    labels = [int(x) for x in match[1].split()]
    if neighbour:
        other = re.search(r"}\s*\d+\s*\((.*?)\)\s*;?\s*$", _plain(neighbour), re.S)
        if not other or not re.fullmatch(r"[\d\s]*", other[1]):
            raise ValueError("Unsupported neighbour labelList")
        labels.extend(int(x) for x in other[1].split())
    cells = max(labels, default=-1) + 1
    if not 0 < cells <= MAX_CELLS:
        raise ValueError("Mesh exceeds local cell cap or is empty; use HPC")
    return cells
