"""Read current case inputs conservatively, without evaluating OpenFOAM directives."""
import argparse
import hashlib
import json
from decimal import Decimal, InvalidOperation
from pathlib import Path
import knowledge as k


def viscosity_state(case_root,proposed_edits=()):
    """Classify explicitly configured blastFoam basic/detonating transport inputs.

    This describes configuration, not the mesh-dependent maximum viscosity.
    Nonconstant models require runtime evaluation; a positive phase coefficient
    alone does not prove the solver's mixture-viscosity branch is active.
    """
    root=Path(case_root).resolve()
    path=k.confined(root,'constant/phaseProperties')
    result={'schema':'case-viscosity-state-v1','path':'constant/phaseProperties',
            'state':'unknown','observations':[], 'reasons':[]}
    if not path.is_file():
        result['reasons'].append('phaseProperties missing');return result
    raw=path.read_bytes();result['sha256']=hashlib.sha256(raw).hexdigest()
    try:text=raw.decode()
    except UnicodeError:
        result['reasons'].append('non-text dictionary');return result
    entries,diagnostics=k.parse_dictionary(text)
    if diagnostics or any(not n['resolved'] or '@' in n['dictionary_path'] for n in entries):
        result['reasons'].append('unresolved, duplicate or unsupported dictionary syntax');return result
    by_path={n['dictionary_path']:n for n in entries}
    if proposed_edits:
        result['state_scope']='hypothetical edits over source bytes; not observed copy state'
        result['proposed_edits']=list(proposed_edits)
        for edit in proposed_edits:
            if edit.get('path')!='constant/phaseProperties' or not isinstance(edit.get('entry'),str):
                result['reasons'].append('unsupported proposed state edit');return result
            key=edit['entry'];value=edit.get('value')
            if value is None:by_path.pop(key,None)
            elif isinstance(value,str):by_path[key]={'value':value,'hypothetical':True}
            else:result['reasons'].append('nontext proposed state edit');return result
    def value(key):return by_path.get(key,{}).get('value','')
    phases=[t for t,_,_ in k.lex(value('phases'))]
    if len(phases)<3 or phases[0]!='(' or phases[-1]!=')' or any(t in '(){}[];' for t in phases[1:-1]):
        result['reasons'].append('explicit nonempty phase list required');return result
    phases=phases[1:-1]
    if len(set(phases))!=len(phases):
        result['reasons'].append('duplicate phase');return result
    scopes=[]
    for phase in phases:
        kind=value(phase+'/type')
        if kind=='basic':scopes.append(phase)
        elif kind=='detonating':scopes.extend([phase+'/reactants',phase+'/products'])
        else:result['reasons'].append('unsupported phase type: '+phase)
    positive=False
    for scope in scopes:
        model=value(scope+'/thermoType/transport')
        key=scope+'/transport/mu'
        obs={'scope':scope,'model':model,'entry':key,'value':value(key)}
        if key in by_path and not by_path[key].get('hypothetical'):
            obs.update({name:by_path[key][name] for name in ('line_start','line_end')})
        result['observations'].append(obs)
        if model!='const':
            result['reasons'].append('nonconstant or absent model: '+scope);continue
        try:mu=Decimal(value(key))
        except InvalidOperation:
            result['reasons'].append('nonliteral or absent mu: '+scope);continue
        if not mu.is_finite() or mu<0:
            result['reasons'].append('invalid mu: '+scope);continue
        positive=positive or mu>0
    if result['reasons']:return result
    result['state']='positive_const_input' if positive else 'all_const_zero'
    result['runtime_branch']='not_evaluated'
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--case-root',type=Path,required=True)
    print(json.dumps(viscosity_state(p.parse_args().case_root),ensure_ascii=False))
