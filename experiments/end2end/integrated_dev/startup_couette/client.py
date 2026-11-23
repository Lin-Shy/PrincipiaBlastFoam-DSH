"""Task-specific public delivery list over the unchanged registration client.

Install beside the frozen cavity_agent/contract_client.py as common/client.py.
"""
import json
from pathlib import Path
import sys
from contract_client import collect, submit


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in ("submit", "collect"):
        raise SystemExit("submit or collect")
    root = Path(__file__).resolve().parent.parent
    result = {"submit": submit, "collect": collect}[sys.argv[1]](root)
    if "required_delivery" in result:
        result["required_delivery"]["other_files"].append("profile.csv")
    print(json.dumps(result, ensure_ascii=False, indent=2))
