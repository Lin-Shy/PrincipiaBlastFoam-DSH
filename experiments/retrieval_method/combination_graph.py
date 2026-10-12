"""Concrete registration declarations from compiler-expanded C++ translation units.

This bounded extractor joins thermophysical aliases, wrapper aliases, runtime
names and actual dictionary-table registration declarations. A typedef, a model
header, or a template's allowed component list alone is not a registration.
Source registration does not assert that a binary contains or loads that code.
"""
import hashlib
import json
import re
from pathlib import Path


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def braced(text,start):
    """Balanced C++ block, ignoring braces within literals and comments."""
    depth=0
    pattern=r'//[^\n]*|/\*[\s\S]*?\*/|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|[{}]'
    for m in re.finditer(pattern,text[start:]):
        if m[0]=='{':depth+=1
        elif m[0]=='}':
            depth-=1
            if depth==0:return start+m.end()
    raise ValueError('unbalanced class body')


def runtime_name(text,cls):
    names=[];evidence=[]
    for m in re.finditer(r'\bclass\s+'+re.escape(cls)+r'\b[^;{}]*\{',text):
        end=braced(text,m.end()-1);body=text[m.end():end-1]
        matches=list(re.finditer(r'\btypeName_?\s*\(\s*\)\s*\{\s*return\s*"(\w+)(<)?"([^{}]*)\}',body))
        # Accept only the reviewed literal form or literal + nested typeName.
        for n in matches:
            suffix=n[3].strip()
            if n[2]:
                if not re.fullmatch(r"\+\s*(?:word\s*\(\s*)?\w+::typeName_?\(\s*\)\s*\)?\s*\+\s*'>'\s*;",suffix):continue
            elif suffix!=';':continue
            names.append(n[1]);evidence.append({'start_offset':m.end()+n.start(),'end_offset':m.end()+n.end(),'text':n[0]})
    if len(names)!=1:raise ValueError('runtime name is absent or ambiguous: '+cls)
    return names[0],evidence[0]


def extract(text):
    ident=r'([A-Za-z_]\w*)'
    physical=re.compile(r'\btypedef\s+'+ident+r'\s*<\s*thermoModel\s*<\s*'+ident+r'\s*<\s*'+ident+r'\s*<\s*'+ident+r'\s*>\s*>\s*>\s*>\s*'+ident+r'\s*;')
    wrapper=re.compile(r'\btypedef\s+'+ident+r'\s*<\s*'+ident+r'\s*<\s*'+ident+r'\s*,\s*'+ident+r'\s*>\s*>\s*'+ident+r'\s*;')
    registration=re.compile(r'\b'+ident+r'::adddictionaryConstructorToTable\s*<\s*'+ident+r'\s*>\s*'+ident+r'\s*;')
    def unique(pattern,key):
        result={}
        for m in pattern.finditer(text):
            value=m[key]
            if value in result:raise ValueError('duplicate alias in translation unit: '+value)
            result[value]=m
        return result
    phys=unique(physical,5);wrap=unique(wrapper,5);records=[];gaps=[];names={}
    def source(m):return {'start_offset':m.start(),'end_offset':m.end(),'text':m[0]}
    for reg in registration.finditer(text):
        if reg[2] not in wrap:
            gaps.append({'registration':source(reg),'reason':'unsupported registered wrapper alias'});continue
        w=wrap[reg[2]]
        if w[3]!=reg[1] or w[4] not in phys:
            gaps.append({'registration':source(reg),'reason':'base mismatch or unsupported physical alias'});continue
        ph=phys[w[4]];classes=[reg[1],w[1],ph[1],ph[2],ph[3],ph[4]]
        try:
            for cls in classes:
                if cls not in names:names[cls]=runtime_name(text,cls)
        except ValueError as exc:
            gaps.append({'registration':source(reg),'reason':str(exc)});continue
        labels=[names[c][0] for c in classes]
        combination='<'.join(labels)+'>'*(len(labels)-1)
        records.append({'combination':combination,'components':dict(zip(('base','type','transport','thermo','equationOfState','specie'),labels)),
            'classes':classes,'energy_wrapper':w[2],'physical_alias':ph[5],'registered_alias':reg[2],
            'registration_symbol':reg[3],'state':'source_registration_declaration',
            'evidence':{'physical_typedef':source(ph),'wrapper_typedef':source(w),'registration':source(reg),
                        'runtime_names':{c:names[c][1] for c in classes}},
            'scope':'This expanded translation unit and exact include/compiler manifest only; binary build/load and physical semantics unverified.'})
    return {'records':records,'unresolved_registrations':gaps,'observed_registration_declarations':len(list(registration.finditer(text)))}


def build(extracted,identity):
    nodes=[];edges=[];unit='translation_unit:'+digest(identity)
    nodes.append({'id':unit,'kind':'expanded_translation_unit','identity':identity})
    for record in extracted['records']:
        key='combination:'+digest(record['components']);rid='registration:'+digest([unit,record['registration_symbol']])
        nodes.append({'id':key,'kind':'model_combination','components':record['components'],'name':record['combination']})
        nodes.append({'id':rid,'kind':'source_registration','state':record['state'],'scope':record['scope'],'evidence':record['evidence'],
                      'energy_wrapper':record['energy_wrapper'],'symbol':record['registration_symbol']})
        edges.extend([{'source':key,'target':rid,'relation':'HAS_SOURCE_REGISTRATION_DECLARATION'},
                      {'source':rid,'target':unit,'relation':'EXPANDED_FROM'}])
    graph={'version':'concrete-combination-v1','nodes':nodes,'edges':edges,'unresolved':extracted['unresolved_registrations'],
           'limits':'No negative global-registration assertion from absent records; no build, live registration, load or physical assertion from declarations.'}
    graph['snapshot']=digest(graph)
    return graph


def lookup(graph,components):
    if digest({k:v for k,v in graph.items() if k!='snapshot'})!=graph['snapshot']:raise ValueError('combination graph changed')
    nodes={n['id']:n for n in graph['nodes']};ids=[n['id'] for n in graph['nodes'] if n['kind']=='model_combination' and n['components']==components]
    if len(ids)!=1:return {'status':'not_observed_in_indexed_translation_units','scope':graph['limits']}
    paths=[]
    for e in graph['edges']:
        if e['source']==ids[0] and e['relation']=='HAS_SOURCE_REGISTRATION_DECLARATION':
            for link in graph['edges']:
                if link['source']==e['target'] and link['relation']=='EXPANDED_FROM':paths.append([nodes[ids[0]],nodes[e['target']],nodes[link['target']]])
    if not paths:return {'status':'not_observed_in_indexed_translation_units','scope':graph['limits']}
    return {'status':'source_registration_declaration','combination':nodes[ids[0]]['name'],'evidence_groups':paths,
            'scope':'Source declarations only; current binary, load and physical semantics unverified.'}


class CombinationGraph:
    """Verify the archived compiler expansion and its captured dependencies."""
    def __init__(self,path):
        path=Path(path).resolve();self.root=path.parent;self.graph=json.loads(path.read_text())
        lookup(self.graph,{})
        inventory=json.loads((self.root/'inventory.json').read_text())
        self.corpus_hashes={}
        for relative,sha in inventory.items():
            source=(self.root/relative).resolve()
            if not source.is_relative_to(self.root) or hashlib.sha256(source.read_bytes()).hexdigest()!=sha:
                raise ValueError('combination source changed')
        raw=(self.root/'expanded.cpp').read_bytes();text=raw.decode()
        for unit in self.graph['nodes']:
            if unit['kind']!='expanded_translation_unit':continue
            identity=unit['identity']
            if identity['inventory_digest']!=digest(inventory) or identity['expanded_sha256']!=hashlib.sha256(raw).hexdigest():
                raise ValueError('combination expansion changed')
            if identity.get('source_root'):
                prefix='sources/'+identity['source_root'].lstrip('/')+'/'
                self.corpus_hashes.update({'manual/source_code/blastfoam/'+p.removeprefix(prefix):s
                    for p,s in inventory.items() if p.startswith(prefix)})
        self.registrations={n['id']:n for n in self.graph['nodes'] if n['kind']=='source_registration'}
        for registration in self.registrations.values():
            ev=registration['evidence']
            for item in [ev['physical_typedef'],ev['wrapper_typedef'],ev['registration'],*ev['runtime_names'].values()]:
                if text[item['start_offset']:item['end_offset']]!=item['text']:
                    raise ValueError('combination evidence span changed')

    def compatible_corpus(self,inventory):
        common=self.corpus_hashes.keys()&inventory.keys()
        return bool(common) and all(self.corpus_hashes[p]==inventory[p] for p in common)

    def summary(self,components):
        result=lookup(self.graph,components)
        if result['status']!='source_registration_declaration':
            return {'registration':'not_observed_in_indexed_translation_unit',
                    'scope':'未在已索引编译单元识别到声明；不能推出全局未注册或不可用。','snapshot':self.graph['snapshot']}
        groups=result['evidence_groups']
        return {'registration':'source_declaration_verified','combination':result['combination'],
                'source':'combination_sources/'+groups[0][1]['id'],
                'snapshot':self.graph['snapshot'],'energy_wrapper':groups[0][1]['energy_wrapper'],
                'scope':'已核对具体模板别名→dictionary注册声明；仅源码，不证明当前二进制构建/加载或物理正确。'}

    def source(self,key):
        if key not in self.registrations:raise ValueError('unknown combination evidence')
        return {'snapshot':self.graph['snapshot'],'registration':self.registrations[key],
                'scope':'Offsets are Unicode character offsets in the hash-verified expanded.cpp; all include files are captured in inventory.json.'}
