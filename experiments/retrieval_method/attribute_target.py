"""Resolve an explicit equality predicate against source-declared phase objects.

Currently supports gamma/heat-capacity-ratio equality only. This is not general
natural-language intent parsing or inference from arbitrary numerical mentions.
"""
import hashlib,re
from decimal import Decimal,InvalidOperation

LABEL=r'(?:比热比(?:\s*[（(]\s*gamma\s*[)）])?|(?<![A-Za-z_])gamma(?![A-Za-z_])|heat[ -]capacity[ -]ratio|specific[ -]heat[ -]ratio)'
NUMBER=r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?'
PREDICATE=re.compile(LABEL+r'(?:\s*(?:为|是|等于|=|equals?|of|is)\s*|\s+)('+NUMBER+r')(?![A-Za-z0-9_.])',re.I)


PRESERVE=re.compile(r'保持(?:原样|不变)|不(?:做|作)?(?:任何)?(?:修改|改变)|(?:keep|leave)\b.*?\b(?:unchanged|intact)|\bpreserve\b',re.I)
COMPARISON=re.compile(r'[<>=≤≥≠]|大于|小于|不等|不是|更大|更小|较大|较小|相同|一样|相等|\b(?:greater|less|higher|lower|larger|smaller|equal|not|than)\b',re.I)


def selector_text(text):
    """Remove bare attribute mentions in explicit preservation clauses only.

    Numeric mentions and comparison syntax are never hidden by preservation.
    This is a bounded language rule, not a general semantic parser.
    """
    chunks=re.split(r'([。；;\n!?！？]|\.(?=\s|$))',text)
    for i,chunk in enumerate(chunks):
        if not PRESERVE.search(chunk):continue
        # Protect all supported predicates before inspecting preservation prose.
        # Any other number/comparison leaves the clause unchanged (fail closed).
        masked=PREDICATE.sub('',chunk)
        if re.search(NUMBER,masked) or COMPARISON.search(masked):continue
        parts=[];last=0
        for match in PREDICATE.finditer(chunk):
            parts += [re.sub(LABEL,'',chunk[last:match.start()],flags=re.I),match.group()]
            last=match.end()
        parts.append(re.sub(LABEL,'',chunk[last:],flags=re.I))
        chunks[i]=''.join(parts)
    return ''.join(chunks)


def resolve_target(engine,case,text):
    if not re.search(LABEL,text,re.I):return None
    text=selector_text(text)
    if not re.search(LABEL,text,re.I):return None
    try:values={Decimal(m.group(1)) for m in PREDICATE.finditer(text)}
    except InvalidOperation:return {'status':'invalid_predicate','attribute':'gamma'}
    # Remaining labels must be supported selectors, not preservation mentions.
    stripped=PREDICATE.sub('',text)
    if len(values)!=1 or re.search(LABEL,stripped,re.I):
        return {'status':'unsupported_or_conflicting_predicate','attribute':'gamma'}
    value=next(iter(values))
    case='tutorials/'+case.removeprefix('tutorials/')
    case=engine.graph.get('aliases',{}).get(case,case)
    path=case+'/constant/phaseProperties'
    if path not in engine.graph['inventory']:return {'status':'attribute_source_missing','attribute':'gamma'}
    root=(engine.skill/'corpus').resolve();file=(root/path).resolve()
    if not file.is_relative_to(root):raise ValueError('attribute source escapes corpus')
    raw=file.read_bytes();sha=hashlib.sha256(raw).hexdigest()
    if sha!=engine.graph['inventory'][path]:raise ValueError('attribute source changed')
    import knowledge as k
    entries,diagnostics=k.parse_dictionary(raw.decode())
    if diagnostics or any('@' in e['dictionary_path'] for e in entries):return {'status':'unresolved_source','attribute':'gamma'}
    declared=[e for e in entries if e['dictionary_path']=='phases' and e['resolved']]
    if len(declared)!=1:return {'status':'unresolved_phase_declaration','attribute':'gamma'}
    match=re.fullmatch(r'\(\s*([A-Za-z_]\w*(?:\s+[A-Za-z_]\w*)*)\s*\)',declared[0]['value'])
    if not match:return {'status':'unresolved_phase_declaration','attribute':'gamma'}
    phases=match[1].split()
    if len(set(phases))!=len(phases):return {'status':'unresolved_phase_declaration','attribute':'gamma'}
    matched=[];observed=[];unresolved=[]
    for phase in phases:
        key=phase+'/equationOfState/gamma'
        candidates=[e for e in entries if e['dictionary_path']==key and e['resolved']]
        if len(candidates)!=1:unresolved.append(phase);continue
        e=candidates[0]
        try:
            number=Decimal(e['value'])
            if not number.is_finite():raise InvalidOperation()
        except InvalidOperation:unresolved.append(phase);continue
        item={'phase':phase,'value':str(number),'entry':key,'start':e['line_start'],'end':e['line_end']}
        observed.append(item)
        if number==value:matched.append(phase)
    status='unique' if len(matched)==1 and not unresolved else 'ambiguous' if len(matched)>1 else 'unresolved_source' if unresolved else 'no_match'
    result={'status':status,'attribute':'gamma','equals':str(value),'matches':matched,'observed':observed,'source':path,'sha256':sha}
    if status=='unique':result['phase']=matched[0]
    return result
