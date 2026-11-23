"""Run a supplied calculator via the frozen old professional profile's native shell."""
import shutil
import sys
from measurement_paired_control import OUT, HERE, read, write, sha, dispatch_tool, grade, DIAGNOSTIC, wave

rows=read(OUT/"offline.json")["rows"]
results=[]
for key in sorted({(r["cohort"],r["task"],r["family"]) for r in rows if r["applicable"]}):
    cohort,task,family=key
    directory=OUT/cohort/task
    calc=directory/"measurement_shell_reference.py"
    shutil.copyfile(HERE/calc.name,calc)
    executable=sys.executable.replace("'","''")
    log=dispatch_tool(OUT/"profiles/old",directory,"pwsh",dict(command=f"& '{executable}' -I -B measurement_shell_reference.py {family}",description="Compute ordinary-fluid measurements from public inputs"))
    write(directory/"old-shell-call.json",log["calls"][0])
    old=read(directory/"old-shell-calculation.json")
    old["evidence"]=read(directory/"professional-before.json")["evidence"]
    path=directory/"old-shell-report.json"
    write(path,old)
    fields=grade(wave.DATA if cohort=="original" else DIAGNOSTIC,task,path)
    after=read(directory/"professional-after.json")
    import math
    match=(len(old["terms"])==len(after["terms"]) and all(abs(a-b)<=1e-8 for a,b in zip(old["terms"],after["terms"]))
           and abs(old["amount"]-after["amount"])<=1e-8 and old["decision"]==after["decision"])
    results.append(dict(cohort=cohort,task=task,family=family,fields=fields,matching_new_within_tolerance=match))
write(OUT/"old_shell_comparison.json",dict(calculator_sha256=sha(HERE/calc.name),rows=results))
