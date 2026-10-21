"""Select complete original source roots by blast use, with no dataset argument."""
import argparse
import hashlib
import json
from pathlib import Path

ROOTS = (
    'manual/markdown',
    'tutorials/blastFoam/freeField', 'tutorials/blastFoam/axisymmetricCharge',
    'tutorials/blastFoam/twoChargeDetonation', 'tutorials/blastFoam/delayedDetonation',
    'tutorials/blastFoam/internalDetonation', 'tutorials/blastFoam/burstingWindow_workshop',
    'tutorials/blastFoam/building3D', 'tutorials/blastFoam/building3DWorkshop',
    'tutorials/blastFoam/mappedBuilding3D',
    'tutorials/blastXiFoam/deflagrationToDetonationTransition',
    'tutorials/blastFSIFoam/flap', 'tutorials/blastFSIFoam/building3D',
    'tutorials/preCICE/flap',
    # Named as technical demonstrations, not validated blast scenarios.
    'tutorials/blastFoam/shockTube_tabulated', 'tutorials/blastFoam/reacting',
    'tutorials/initializeAtmosphere', 'tutorials/setRefinedFields',
)
EXCLUDED_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.gif', '.pdf', '.eps', '.svg', '.webp', '.mp4'}

def sha(raw):return hashlib.sha256(raw).hexdigest()
def write(p,v):
    p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

def prepare(corpus,output):
    corpus=corpus.resolve();files=[];excluded=[];missing=[]
    selected=set()
    for root in ROOTS:
        base=corpus/root
        if not base.is_dir():missing.append(root);continue
        for p in base.rglob('*'):
            if not p.is_file():continue
            relative=p.relative_to(corpus).as_posix()
            resolved=p.resolve()
            if not resolved.is_relative_to(corpus):raise ValueError('source symlink escaped original corpus')
            if p.suffix.casefold() in EXCLUDED_EXTENSIONS or any(part.startswith('.') for part in p.relative_to(corpus).parts):
                excluded.append({'path':relative,'reason':'nontext_or_hidden_asset'});continue
            if relative in selected:continue
            raw=p.read_bytes()
            try:text=raw.decode('utf-8')
            except UnicodeError:
                excluded.append({'path':relative,'reason':'not_utf8_text'});continue
            if '\x00' in text:
                excluded.append({'path':relative,'reason':'binary_content'});continue
            selected.add(relative)
            files.append({'path':relative,'sha256':sha(raw),'bytes':len(raw),'lines':len(text.splitlines())})
    if missing:raise ValueError('independent source root missing: '+str(missing))
    files.sort(key=lambda r:r['path'])
    value={'schema':'independent_blast_knowledge_corpus_v1','files':files,
        'scope_policy':'Whole manual plus complete actual blast/detonation/FSI case roots; table, reacting, atmosphere and refined-field tutorials are explicit technical/environmental demonstrations. No question/gold/evidence-side selection.',
        'included_roots':list(ROOTS),'excluded_extensions':sorted(EXCLUDED_EXTENSIONS),
        'selection_implementation_sha256':sha(Path(__file__).read_bytes())}
    manifest=output/'corpus-manifest.json'
    if manifest.exists():
        if json.loads(manifest.read_text(encoding='utf-8'))!=value:raise ValueError('corpus manifest changed: create a new setup revision')
    write(manifest,value)
    # Old neutral backend adapters expect a path -> sha mapping. This derived
    # manifest contains exactly the same raw files; it is not scoring evidence.
    write(output/'backend-source-map.json',{'schema':'original_source_hash_map_v1','files':{f['path']:f['sha256'] for f in files}})
    audit={'manifest_sha256':sha(manifest.read_bytes()),'files':len(files),'bytes':sum(f['bytes'] for f in files),
        'excluded':excluded,'missing_roots':missing,'questions_read':False,'gold_read':False,
        'source_copy':False,'implementation_sha256':sha(Path(__file__).read_bytes())}
    write(output/'selection-audit.json',audit)
    return audit

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--corpus',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();result=prepare(args.corpus,args.output)
    print(json.dumps({k:result[k] for k in ('files','bytes','questions_read','gold_read','missing_roots')}))

if __name__=='__main__':main()
