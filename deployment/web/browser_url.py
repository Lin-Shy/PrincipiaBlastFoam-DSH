from pathlib import Path
import re
s=Path("/data/chapter3-agent-development/workspace/services/chapter3-web-20261123/web.stdout").read_text()
m=re.search(r"dsh web: (http://127[.]0[.]0[.]1:3080/\S+)",s)
print(m.group(1) if m else "NOT_READY")
