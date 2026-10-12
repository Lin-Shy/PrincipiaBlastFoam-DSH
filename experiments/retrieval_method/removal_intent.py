"""Finite explicit removal clauses, bound to an already selected coefficient scope.

No automatic deletion from a destination schema's absent keys. Unknown removal
clauses and explicit other-object targets require review instead of guessing.
"""
import re

REMOVE=r'删除|删去|移除|不再保留|\bremove\b|\bdelete\b|\bno longer retain\b'
KEEP=r'保留|保持|\bkeep\b|\bpreserve\b|\bleave\b'


def requested_removals(text,scope,keys,aliases=None):
    aliases=aliases or {};removed=set();kept=set();unresolved=False
    phase=scope.split('/')[0]
    clauses=re.split(r'[；;。\n]|[,，](?=\s*(?:保留|保持|另一|其余|不要|keep|preserve|leave|another|do not|remove|delete|删除|移除))',text,flags=re.I)
    for clause in clauses:
        remove=re.search(REMOVE,clause,re.I);keep=re.search(KEEP,clause,re.I)
        if remove and keep and remove.start()<=keep.start()<keep.end()<=remove.end():keep=None
        if not remove and not keep:continue
        if remove and keep:
            unresolved=True;continue
        objects=clause[remove.end():] if remove else clause
        selected={key for key in keys if re.search(r'(?<![A-Za-z0-9_])'+re.escape(key)+r'(?![A-Za-z0-9_])',objects)
                  or any(alias in objects for alias in aliases.get(key,[]))}
        negated=bool(remove and re.search(r'(?:不|不要|勿|do\s+not|don.t|never|without)\s*$',clause[:remove.start()],re.I))
        other=bool(re.search(r'另一|其他相|两相|所有相|\bother\b|\bboth\b',clause,re.I))
        owner=re.search(r'(?:'+REMOVE+'|'+KEEP+r')\s*([A-Za-z_][A-Za-z0-9_]*)\s*(?:的|相|\s+phase\b)',clause,re.I)
        if owner and owner[1]!=phase:other=True
        for path in re.findall(r'(?:[A-Za-z_][A-Za-z0-9_]*/)+[A-Za-z_][A-Za-z0-9_]*',clause):
            if path.rsplit('/',1)[-1] in selected and path!=scope+'/'+path.rsplit('/',1)[-1]:other=True
        if remove and not negated:
            words=set(re.findall(r'[A-Za-z_][A-Za-z0-9_]*',clause[remove.end():]))
            grammar={'the','old','original','fixed','viscosity','parameter','parameters','coefficient','coefficients',
                     'and','of','from','phase','target','const'}
            unknown={w for w in words if w not in keys and w not in scope.split('/') and w.lower() not in grammar}
            if other or not selected or unknown:unresolved=True
            else:removed.update(selected)
        elif (keep or negated) and not other:kept.update(selected)
    if removed & kept:return {'status':'conflicting_removal','keys':[]}
    if unresolved:return {'status':'unresolved_removal','keys':[]}
    return {'status':'resolved','keys':sorted(removed)}
