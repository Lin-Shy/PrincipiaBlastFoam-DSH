"""Freeze a TU's includes, expand C++ macros and construct concrete combination evidence."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import time
from experiments.retrieval_method.combination_graph import extract,build,digest


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    p=argparse.ArgumentParser();p.add_argument('--thermodynamics-root',type=Path,required=True)
    p.add_argument('--translation-unit',required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();root=a.thermodynamics_root.resolve();out=a.output.resolve();out.mkdir(parents=True,exist_ok=False)
    builder_dir=out/'builder-source';builder_dir.mkdir()
    builder_identity={}
    for name in ('combination_graph.py','build_combination_graph.py'):
        file=Path(__file__).with_name(name);shutil.copy2(file,builder_dir/name)
        builder_identity[name]=sha(builder_dir/name)
    unit=(root/a.translation_unit).resolve()
    if not unit.is_relative_to(root) or not unit.is_file():raise ValueError('translation unit escapes thermodynamics root')
    project=Path(os.environ['WM_PROJECT_DIR']);variables={'LIB_SRC':str(project/'src'),'BLAST_DIR':str(root.parent.parent)}
    incs=[root/'lnInclude',root,project/'src/OpenFOAM/lnInclude',project/'src/OSspecific/POSIX/lnInclude']
    for m in re.finditer(r'-I([^\s\\]+)',(root/'Make/options').read_text()):
        value=m[1]
        for key,val in variables.items():value=value.replace('$('+key+')',val)
        if '$' in value:raise ValueError('unresolved compiler include variable')
        incs.append(Path(value))
    compiler=shutil.which('g++');flags=['-std=c++11','-Dlinux64','-DWM_ARCH_OPTION=64','-DWM_DP','-DWM_LABEL_SIZE=32','-DNoRepository',*['-I'+str(i) for i in incs]]
    start=time.perf_counter();dep=subprocess.run([compiler,*flags,'-M',str(unit)],capture_output=True,text=True,check=True)
    (out/'dependencies.make').write_text(dep.stdout)
    paths=[Path(s).resolve() for s in shlex.split(dep.stdout.split(':',1)[1].replace('\\\n',' '))]
    paths += [root/'Make/options',root/'Make/files']
    before={str(path):sha(path) for path in sorted(set(paths))}
    command=[compiler,*flags,'-E','-P',str(unit)]
    with (out/'expanded.cpp').open('w') as stdout,(out/'preprocessor.stderr').open('w') as stderr:
        process=subprocess.run(command,stdout=stdout,stderr=stderr,check=True)
    if any(sha(path)!=s for path,s in before.items()):raise ValueError('preprocessing sources changed during capture')
    inventory={}
    for path,s in before.items():
        source=Path(path);relative='sources/'+str(source).lstrip('/');target=out/relative
        target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
        if sha(target)!=s:raise ValueError('source changed while freezing')
        inventory[relative]=s
    (out/'inventory.json').write_text(json.dumps(inventory,indent=2))
    metrics={'preprocessing_seconds':time.perf_counter()-start}
    cc1=Path(subprocess.run([compiler,'-print-prog-name=cc1plus'],capture_output=True,text=True,check=True).stdout.strip()).resolve()
    identity={'command':command,'compiler_sha256':sha(compiler),'cc1plus_sha256':sha(cc1),'compiler_version':subprocess.run([compiler,'--version'],capture_output=True,text=True,check=True).stdout.splitlines()[0],
              'translation_unit':str(unit),'source_sha256':before[str(unit)],'expanded_sha256':sha(out/'expanded.cpp'),
              'source_root':str(root.parent.parent),'inventory_digest':digest(inventory),'dependency_files':len(inventory),
              'extractor_sha256':sha(Path(__file__).with_name('combination_graph.py')),
              'builder_source':builder_identity,
              'build_manifest_link':a.translation_unit in (root/'Make/files').read_text().splitlines(),
              'source_version_scope':'Exact captured source hashes; installed-source HEAD alone does not assert clean source or binary correspondence.'}
    start=time.perf_counter();parsed=extract((out/'expanded.cpp').read_text());graph=build(parsed,identity)
    (out/'extraction.json').write_text(json.dumps(parsed,indent=2));(out/'graph.json').write_text(json.dumps(graph,indent=2))
    metrics['extraction_seconds']=time.perf_counter()-start
    (out/'identity.json').write_text(json.dumps(identity,indent=2))
    (out/'metrics.json').write_text(json.dumps(metrics,indent=2))
    print(json.dumps({'combinations':len(parsed['records']),'observed_declarations':parsed['observed_registration_declarations'],
                      'unresolved':len(parsed['unresolved_registrations']),'dependency_files':len(inventory),
                      'seconds':metrics['preprocessing_seconds']+metrics['extraction_seconds'],'snapshot':graph['snapshot']}))


if __name__=='__main__':main()
