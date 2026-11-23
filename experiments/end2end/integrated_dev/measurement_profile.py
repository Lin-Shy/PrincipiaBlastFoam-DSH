"""Install the revision's measurement tools in an ordinary-fluid development profile."""
from pathlib import Path
import shutil

HERE = Path(__file__).resolve().parent
PLUGIN = HERE / "measurement-audit.mjs"


def extend_profile(profile, root):
    shutil.copytree(HERE / "measurement-review", root / "skills" / "measurement-review")
    return profile + "\n- id: measurement-audit\n  name: " + PLUGIN.as_uri() + "\n"
