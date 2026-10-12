"""Import pinned source bytes; assess extraction with an unchanged source set.

No working-tree solver files are changed or trusted over their Git object.
Experimental output is required to reside outside the application repository.
"""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def run(repository, *args):
    return subprocess.check_output(['git', '-C', str(repository), *args])


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--repository',type=Path,required=True)
    p.add_argument('--commit',required=True)
    p.add_argument('--skill',type=Path,required=True)
    p.add_argument('--baseline',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();root=Path(__file__).resolve().parents[2]
    out=a.output.resolve()
    if out.is_relative_to(root):raise ValueError('results must be outside source repository')
    out.mkdir(parents=True,exist_ok=False)
    commit=run(a.repository,'rev-parse',a.commit+'^{commit}').decode().strip()
    prefix='src/thermodynamicModels/specie/'
    files=run(a.repository,'ls-tree','-r','--name-only',commit,'--',prefix).decode().splitlines()
    files=[f for f in files if Path(f).suffix in ('.C','.H')]
    source_root=a.skill/'corpus/manual/source_code';provenance_path=source_root/'provenance.json'
    provenance=json.loads(provenance_path.read_text());by_path={(x['repository'],x['path']):x for x in provenance}
    imported=[]
    for file in files:
        raw=run(a.repository,'show',commit+':'+file)
        target=source_root/'blastfoam'/file;target.parent.mkdir(parents=True,exist_ok=True)
        if target.is_file() and target.read_bytes()!=raw:raise ValueError('conflicting fixed source '+file)
        target.write_bytes(raw)
        entry={'repository':'blastfoam','commit':commit,'path':file,'sha256':digest(raw)}
        by_path['blastfoam',file]=entry;imported.append(entry)
    provenance_path.write_text(json.dumps(list(by_path.values()),ensure_ascii=False,indent=2)+'\n')
    (out/'source-manifest.json').write_text(json.dumps(imported,indent=2))
    # Load the old function alone, so both methods see precisely the same bytes.
    old=ast.parse(a.baseline.read_text())
    fn=next(n for n in old.body if isinstance(n,ast.FunctionDef) and n.name=='literal_input_schema')
    ns={'re':re};exec(compile(ast.Module(body=[fn],type_ignores=[]),str(a.baseline),'exec'),ns)
    sys.path.insert(0,str(a.skill/'scripts'));import cpp_inputs
    (out/'candidate-parser.py').write_bytes(Path(cpp_inputs.__file__).read_bytes())
    identity={'commit':commit,'parser_sha256':digest(Path(cpp_inputs.__file__).read_bytes()),
              'baseline_sha256':digest(a.baseline.read_bytes()),'construction_api_tokens':0}
    (out/'identity.json').write_text(json.dumps(identity,indent=2))
    records=[]
    for file in files:
        header=str(Path(file).with_suffix('.H'))
        if not file.endswith('.C') or header not in files:continue
        source=(source_root/'blastfoam'/file).read_text();h=(source_root/'blastfoam'/header).read_text()
        start=time.perf_counter();before=ns['literal_input_schema'](source,h);old_seconds=time.perf_counter()-start
        start=time.perf_counter();after=cpp_inputs.analyze(source,h);new_seconds=time.perf_counter()-start
        records.append({'path':file,'baseline':before,'candidate':after,
                        'baseline_seconds':old_seconds,'candidate_seconds':new_seconds})
    (out/'extraction.json').write_text(json.dumps(records,ensure_ascii=False,indent=2))
    print(json.dumps({'imported_files':len(files),'source_pairs':len(records),
          'baseline_recognized_pairs':sum(r['baseline'] is not None for r in records),
          'candidate_recognized_pairs':sum(any(m['dictionary_only_constructor'] and m['inputs'] for m in r['candidate']['models']) for r in records),
          'baseline_seconds':sum(r['baseline_seconds'] for r in records),
          'candidate_seconds':sum(r['candidate_seconds'] for r in records)}))


if __name__=='__main__':main()
