"""Current five-level contract. Legacy records are rejected, never reinterpreted."""
import hashlib
import json
import math
from pathlib import Path
RULES=json.loads(Path(__file__).with_name('scoring_rules.json').read_text(encoding='utf-8'))
VERSION=RULES['schema_version']
LEVELS=RULES['levels']
JUDGES=['human','gpt_sol','deepseek_flash']
SUPPORTED_JUDGES=JUDGES

def exact(obj,required,optional=()):
    if not isinstance(obj,dict) or not set(required)<=set(obj) or set(obj)-set(required)-set(optional):
        raise ValueError('Unexpected or missing contract fields')

def is_score(v):return v=='unknown' or type(v) in (int,float) and v in LEVELS

def is_gate(v,na=False):
    # Compatibility name: a graded score, never a hard gate.
    return is_score(v) or na and v=='not_applicable'

def validate(record,phase='joint',expected=None,conditional=None):
    if phase not in ('coverage','evidence','joint'):raise ValueError('Unknown phase')
    required=['schema_version','sample_id','judge_id','judge_version','status']
    required+=['points'] if phase=='coverage' else ['fact_gate','applicability_gate'] if phase=='evidence' else ['points','fact_gate','applicability_gate']
    exact(record,required,['reason'])
    if record['schema_version']!=VERSION:raise ValueError('Legacy semantics: retain evidence and rescore with current prompt')
    if record['judge_id'] not in JUDGES or record['status']!='complete':raise ValueError('Invalid judge/status')
    if any(not isinstance(record[k],str) or not record[k].strip() for k in ('sample_id','judge_version')):raise ValueError('Empty identity')
    if not isinstance(record.get('reason',''),str):raise ValueError('Invalid note')
    if phase!='evidence':
        if not isinstance(record['points'],list) or not record['points']:raise ValueError('Missing points')
        ids=[]
        for point in record['points']:
            exact(point,['criterion_id','score'],['reason','answer_quote'])
            if not isinstance(point['criterion_id'],str) or not point['criterion_id'] or not is_score(point['score']):raise ValueError('Invalid point')
            if any(not isinstance(point[k],str) for k in ('reason','answer_quote') if k in point):raise ValueError('Invalid point note')
            ids.append(point['criterion_id'])
        if len(set(ids))!=len(ids) or expected is not None and set(ids)!=set(expected):raise ValueError('Duplicate/mismatched criteria')
    if phase!='coverage':
        if not is_score(record['fact_gate']) or not is_gate(record['applicability_gate'],True):raise ValueError('Invalid five-level F/A')
        a=record['applicability_gate']
        if conditional is True and a=='not_applicable' or conditional is False and a!='not_applicable':raise ValueError('A conditional status mismatch')
    return record

def bounds(value):
    if value is None or value=='unknown':return (0.,1.)
    if not is_score(value):raise ValueError('Invalid score in calculation')
    return (float(value),float(value))

def calculate(points,f,a,conditional,generation_failed=False):
    """None=missing, unknown=explicitly unjudgeable. All denominators stay fixed."""
    if not points:raise ValueError('At least one necessary point required')
    if conditional and a=='not_applicable' or not conditional and a!='not_applicable':raise ValueError('A conditional status mismatch')
    kb=[sum(bounds(v)[j] for v in points)/len(points) for j in (0,1)]
    values=list(points)+[f]+([a] if conditional else [])
    dims=[tuple(kb),bounds(f)]+([bounds(a)] if conditional else [])
    ab=[100*sum(d[j] for d in dims)/len(dims) for j in (0,1)]
    gb=[100*math.prod(d[j] for d in dims)**(1/len(dims)) for j in (0,1)]
    sb=[int(all(bounds(v)[j]==1 for v in values)) for j in (0,1)]
    uncertain=any(v is None or v=='unknown' for v in values)
    if generation_failed:ab=[0.,0.];gb=[0.,0.];sb=[0,0]
    return dict(K=None if any(v is None or v=='unknown' for v in points) else kb[0],F=f,A=a,
        EAS_arith=None if uncertain and not generation_failed else ab[0],
        EAS_geo=None if uncertain and not generation_failed else gb[0],Strict=sb[0] if sb[0]==sb[1] else None,
        coverage_bounds=kb,eas_arith_bounds=ab,eas_geo_bounds=gb,strict_bounds=sb,missing_items=sum(v is None for v in values),
        unknown_items=sum(v=='unknown' for v in values),generation_failed=generation_failed,schema_version=VERSION)

def joint_metrics(record,criteria,conditional,generation_failed=False):
    validate(record,'joint',criteria,conditional)
    z={p['criterion_id']:p['score'] for p in record['points']}
    return calculate([z[k] for k in criteria],record['fact_gate'],record['applicability_gate'],conditional,generation_failed)

def metrics(coverage,evidence,weights,conditional,generation_failed=False):
    """Compatibility adapter: weight KEYS identify criteria; numbers are unused."""
    validate(coverage,'coverage',weights);validate(evidence,'evidence',conditional=conditional)
    if any(coverage[k]!=evidence[k] for k in ('sample_id','judge_id','judge_version')):raise ValueError('Mismatched score identities')
    return joint_metrics(dict(coverage,fact_gate=evidence['fact_gate'],applicability_gate=evidence['applicability_gate']),weights,conditional,generation_failed)

def schema(phase='joint'):
    if phase not in ('coverage','evidence','joint'):raise ValueError('Unknown phase')
    score={'enum':LEVELS+['unknown']}
    props=dict(schema_version={'const':VERSION},sample_id={'type':'string','minLength':1},judge_id={'enum':JUDGES},judge_version={'type':'string','minLength':1},status={'const':'complete'})
    if phase in ('coverage','joint'):
        props['points']={'type':'array','minItems':1,'items':{'type':'object','additionalProperties':False,'required':['criterion_id','score'],'properties':{'criterion_id':{'type':'string','minLength':1},'score':score,'reason':{'type':'string'},'answer_quote':{'type':'string'}}}}
    if phase in ('evidence','joint'):props.update(fact_gate=score,applicability_gate={'enum':LEVELS+['unknown','not_applicable']})
    required=list(props);props['reason']={'type':'string'}
    return {'$schema':'https://json-schema.org/draft/2020-12/schema','type':'object','additionalProperties':False,'required':required,'properties':props}

def validate_sources(record,corpus,manifest):
    root=Path(corpus).resolve()
    for claim in record.get('claim_audit',[]):
        for ref in claim['source_references']:
            p=(root/ref['path']).resolve()
            if not p.is_relative_to(root) or ref['path'] not in manifest or hashlib.sha256(p.read_bytes()).hexdigest()!=manifest[ref['path']]:raise ValueError('Frozen source mismatch')
            if ref['line_end']>len(p.read_text(encoding='utf-8-sig').splitlines()):raise ValueError('Reference exceeds source')
    return True

class PacketReader:
    def __init__(self,root):self.root=Path(root).resolve()
    def read(self,path):
        p=(self.root/path).resolve()
        if not p.is_relative_to(self.root):raise PermissionError('Outside assigned packet')
        return p.read_text(encoding='utf-8-sig')
