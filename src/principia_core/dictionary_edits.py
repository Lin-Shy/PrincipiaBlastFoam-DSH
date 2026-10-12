"""Apply explicit dictionary edits on a staged copy before publishing changed files.

No retrieval or physics inference: the caller supplies every path, key and value.
"""
from __future__ import annotations
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile


def _entry(value: str) -> str:
    parts=value.split('/')
    if not value or any(not p or p in ('.','..') or any(c in p for c in '\n\r\";$#{}') for p in parts):
        raise ValueError('invalid dictionary entry')
    if parts[0]=='FoamFile':raise ValueError('header edits are unsupported')
    return '/'.join(parts[:-1]+['"'+parts[-1]+'"' if parts[-1].startswith('(') and parts[-1].endswith(')') else parts[-1]])


def _check_value(value: str) -> None:
    stack=[]
    for match in re.finditer(r'"(?:\\.|[^"\\])*"|//[^\n]*|/\*[\s\S]*?\*/|.',value,re.S):
        token=match.group()
        if token.startswith(('//','/*')) or (token.startswith('"') and len(token)>1):continue
        if token=='"':raise ValueError('unterminated quoted value')
        if token in ('{','(','['):stack.append(token)
        elif token in ('}',')',']'):
            if not stack or stack.pop()!={'}':'{',')':'(',']':'['}[token]:raise ValueError('unbalanced value')
        elif token==';' and not stack:raise ValueError('value must not inject sibling entries or include its terminal semicolon')
    if stack:raise ValueError('unbalanced value')


def _run(path: Path, *args: str) -> str:
    p=subprocess.run(['foamDictionary',str(path),*args],capture_output=True,text=True,timeout=20)
    if p.returncode:raise ValueError('foamDictionary: '+p.stderr[-1600:])
    return p.stdout


def _keys(path: Path, parent: str) -> set[str]:
    text=_run(path,*(['-entry',parent] if parent else []),'-keywords')
    return {line.strip().strip('"') for line in text.splitlines() if line.strip()}


def _bytes(path: Path):
    return path.read_bytes() if path.exists() else None


def _effective_group_lookups(stage: Path, operations: list[tuple]) -> dict:
    """Observe finite parent alternatives through OpenFOAM's own lookup rules.

    This does not expand arbitrary regexes or infer which fields a solver uses.
    A dormant group may be intentional, so mismatches are feedback, not rejection.
    """
    checks=[];seen=set();limited=False
    for rel,entry,value in operations:
        if value is None:continue
        parts=entry.split('/')
        groups=[i for i,p in enumerate(parts[:-1])
                if re.fullmatch(r'\([A-Za-z_]\w*(?:\|[A-Za-z_]\w*)+\)',p)]
        if len(groups)!=1:continue
        index=groups[0]
        for name in parts[index][1:-1].split('|'):
            concrete='/'.join(parts[:index]+[name]+parts[index+1:])
            key=(rel,entry,concrete)
            if key in seen:continue
            seen.add(key)
            if len(checks)>=32:
                limited=True;continue
            item={'path':rel,'group_entry':entry,'lookup_entry':concrete}
            try:
                group=_run(stage/rel,'-entry',entry,'-value').strip()
                effective=_run(stage/rel,'-entry',concrete,'-value').strip()
                item.update(group_value=group,effective_value=effective,
                            matches_group=group.split()==effective.split())
            except ValueError as exc:
                item.update(matches_group=None,error=str(exc))
            checks.append(item)
    status=('not_checked' if not checks else 'partial' if limited or any(c['matches_group'] is None for c in checks) else 'checked')
    mismatch=any(c['matches_group'] is False for c in checks)
    return {'status':status,'checks':checks,
            'has_mismatch':True if mismatch else False if status=='checked' else None,
            'checked_lookups':sum(c['matches_group'] is not None for c in checks),
            'interpretation':'Only listed finite-group lookups were checked. Empty checks do not validate literal-key precedence or runtime behavior.',
            'limited':limited,
            'scope':'final staged values via foamDictionary; one finite literal-alternative parent per edited entry, at most 32 checks; arbitrary regexes and runtime validity not checked'}


def apply_dictionary_edits(case_path: str | Path, edits: list[dict], *, dry_run: bool=False) -> dict:
    """Set/remove literal keys; create missing parents and system/constant dictionaries.

Values are OpenFOAM text; null removes an existing literal entry. All touched files
are parsed before publication. Directives/substitutions need a different editor.
"""
    case=Path(case_path).resolve()
    if not case.is_dir():raise ValueError('case directory does not exist')
    if not isinstance(edits,list) or not 1<=len(edits)<=64:raise ValueError('edits must contain 1..64 operations')
    originals={};operations=[]
    for edit in edits:
        if not isinstance(edit,dict) or set(edit)!={'path','entry','value'}:raise ValueError('each edit requires path, entry, value')
        rel=edit['path'];entry=edit['entry'];value=edit['value']
        if not isinstance(rel,str) or not re.fullmatch(r'(constant|system|0)/[\w.-]+',rel):raise ValueError('only direct case dictionary files are supported')
        if not isinstance(entry,str):raise ValueError('entry must be text')
        _entry(entry)
        if value is not None and (not isinstance(value,str) or not value.strip() or len(value)>16000 or '#' in value or '$' in value):raise ValueError('invalid value or unsupported directive/substitution')
        if value is not None:_check_value(value)
        target=case/rel
        if target.is_symlink() or target.parent.is_symlink() or not target.resolve().is_relative_to(case):raise ValueError('symlinked dictionaries are unsupported')
        if rel not in originals:
            raw=_bytes(target)
            if raw is None and rel.startswith('0/'):raise ValueError('new field headers must be supplied separately')
            if raw is not None and ('#' in raw.decode() or '$' in raw.decode()):raise ValueError('directives/substitutions require an explicit editor')
            originals[rel]=raw
        operations.append((rel,entry,value))
    with tempfile.TemporaryDirectory(prefix='principia-dictionary-') as folder:
        stage=Path(folder)
        for rel,raw in originals.items():
            path=stage/rel;path.parent.mkdir(parents=True,exist_ok=True)
            path.write_bytes(raw if raw is not None else ('FoamFile { version 2.0; format ascii; class dictionary; object '+path.name+'; }\n').encode())
            _run(path,'-keywords')
        changes=[]
        for rel,entry,value in operations:
            path=stage/rel;parts=entry.split('/')
            for i in range(len(parts)-1):
                parent='/'.join(parts[:i]);name=parts[i];full='/'.join(parts[:i+1])
                if name not in _keys(path,parent):
                    if value is None:raise ValueError('cannot remove missing literal entry: '+entry)
                    _run(path,'-entry',_entry(full),'-add','{}')
            exists=parts[-1] in _keys(path,'/'.join(parts[:-1]))
            if value is None and not exists:raise ValueError('cannot remove missing literal entry: '+entry)
            _run(path,'-entry',entry if exists else _entry(entry),*(['-remove'] if value is None else ['-set' if exists else '-add',value]))
            changes.append({'path':rel,'entry':entry,'value':value})
        updates={}
        for rel in originals:
            _run(stage/rel,'-keywords');updates[rel]=(stage/rel).read_bytes()
        effective_lookups=_effective_group_lookups(stage,operations)
        # External edits during preparation must never be silently overwritten.
        if any(_bytes(case/rel)!=raw for rel,raw in originals.items()):raise ValueError('case changed during preparation')
        if not dry_run:
            published=[]
            try:
                for rel,raw in updates.items():
                    target=case/rel;target.parent.mkdir(parents=True,exist_ok=True)
                    fd,name=tempfile.mkstemp(prefix='.dictionary-',dir=target.parent)
                    try:
                        with os.fdopen(fd,'wb') as file:file.write(raw)
                        if target.exists():shutil.copymode(target,name)
                        os.replace(name,target);published.append(rel)
                    finally:
                        if os.path.exists(name):os.unlink(name)
            except Exception:
                for rel in reversed(published):
                    if originals[rel] is None:(case/rel).unlink()
                    else:(case/rel).write_bytes(originals[rel])
                raise
    return {'status':'validated' if dry_run else 'applied','edits':changes,
            'effective_lookups':effective_lookups,
            'files':[{'path':rel,'before_sha256':hashlib.sha256(originals[rel]).hexdigest() if originals[rel] is not None else None,
                      'after_sha256':hashlib.sha256(raw).hexdigest()} for rel,raw in updates.items()],
            'validation':'OpenFOAM dictionary parsing only; no physical or runtime validation'}
