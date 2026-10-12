"""同一include基础图/代码，只切换参数结构层：off/nodes/aligned/candidates。"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def read(path):return json.loads(path.read_text())
def save(path,data):path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--base-skill',type=Path,required=True)
    p.add_argument('--candidate-scripts',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    shutil.copy2(__file__,a.output/'driver.py')
    rows=[]; source_inventory=None
    for mode in ('off','nodes','aligned','candidates'):
        folder=a.output/mode; skill=folder/'skill'
        shutil.copytree(a.base_skill,skill,ignore=shutil.ignore_patterns('__pycache__','cache'))
        for name in ('task_structure.py','task_evidence.py','manual_parameters.py'):
            shutil.copy2(a.candidate_scripts/name,skill/'scripts'/name)
        started=time.monotonic()
        proc=subprocess.run([sys.executable,str(skill/'scripts/task_structure.py'),'--skill',str(skill),'--mode',mode],capture_output=True,text=True)
        save(folder/'build-process.json',{'exit_code':proc.returncode,'stdout':proc.stdout,'stderr':proc.stderr,'seconds':time.monotonic()-started})
        if proc.returncode:raise RuntimeError('construction failed; process record preserved in '+str(folder))
        release=skill/'index/releases'/read(skill/'index/current.json')['snapshot']
        manifest=read(release/'manifest.json');graph=read(release/'graph.json')
        if source_inventory is None:source_inventory=manifest['inventory']
        if source_inventory!=manifest['inventory']:raise ValueError('source mismatch between arms')
        nodes={n['id']:n for n in graph['nodes']};alignments=[e for e in graph['edges'] if e['relation'].startswith('PARAMETER_INSTANCE')]
        for edge in alignments:
            for ev in edge['supporting_evidence']:
                source=skill/'corpus'/ev['path']; lines=source.read_text().splitlines()
                if sha(source)!=ev['sha256'] or not 1<=ev['line_start']<=ev['line_end']<=len(lines):raise ValueError('alignment provenance mismatch')
        audit=[{'relation':e['relation'],'status':e['status'],'model':nodes[e['selector']]['value'],
                'case':nodes[e['source']].get('case'),'file':nodes[e['source']]['evidence']['path'],
                'dictionary_path':nodes[e['source']]['dictionary_path'],'instance_value':nodes[e['source']]['value'],
                'manual_parameter':nodes[e['target']]['label'],'manual_section':nodes[e['target']]['evidence']['section'],
                'match_rule':e['match_rule'],'evidence':e['supporting_evidence']} for e in alignments]
        save(folder/'alignment-audit.json',audit)
        row={'mode':mode,'snapshot':graph['snapshot'],'parameters':graph['task_structure']['parameters'],
             'selector_records':len(graph['task_structure']['selectors']),'alignments':len(alignments),
             'cases':len({r['case'] for r in audit}),'models':sorted({r['model'] for r in audit}),
             'statuses':dict(Counter(e['status'] for e in alignments)),'llm_calls':0,'llm_tokens':0,
             'files':{p.relative_to(folder).as_posix():sha(p) for p in sorted(folder.rglob('*')) if p.is_file() and '__pycache__' not in p.parts and 'cache' not in p.parts}}
        save(folder/'construction.json',row);rows.append({k:v for k,v in row.items() if k!='files'})
    save(a.output/'ablation.json',{'source_inventory_equal':True,'conditions':rows,'driver_sha256':sha(a.output/'driver.py'),
        'factor_order':['off to nodes: manual parameter granularity','nodes to aligned: deterministic model/key/physical-scope edges','aligned to candidates: explicitly uncertain notation/include candidates'],
        'not_changed':['corpus','legacy ranking and expansion','prompts','budgets','model'],'qa_claim':'No answer quality claim from construction or provenance checks.'})
    print(json.dumps(rows,ensure_ascii=False))


if __name__=='__main__':main()
