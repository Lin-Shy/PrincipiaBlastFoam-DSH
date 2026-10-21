import importlib.util
from pathlib import Path
import sys
import hashlib
import json

MODULES=Path(__file__).resolve().parents[1]/'experiments/retrieval_method'
sys.path.insert(0,str(MODULES))
import chapter2_graph_sources as sources
from principia_core.retrieval.knowledge_qa import FrozenKnowledgeCorpus

def corpus(tmp_path,files):
    rows=[]
    for name,text in files.items():
        p=tmp_path/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text,encoding='utf-8')
        rows.append({'path':name,'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'bytes':len(p.read_bytes()),'lines':len(text.splitlines())})
    m=tmp_path/'manifest.json';m.write_text(json.dumps({'schema':'independent_blast_knowledge_corpus_v1','files':rows}))
    return FrozenKnowledgeCorpus(tmp_path,m)

def test_markdown_heading_in_fence_is_not_a_source_boundary():
    lines=['# Models','intro','```foam','#include "file"','```','## First','value','## Second','other']
    parts=sources.markdown_ranges(lines)
    assert [(r['start'],r['end']) for r in parts]==[(1,5),(6,7),(8,9)]
    assert parts[1]['context'][0]['title']=='Models'

def test_config_source_owners_separate_reactants_products_and_functions(tmp_path):
    text='FoamFile { format ascii; }\nRDX\n{\n reactants\n {\n  thermoType { equationOfState Murnaghan; }\n }\n products\n {\n  thermoType { equationOfState JWL; }\n }\n}\nfunctions\n{\n overpressure { type overpressure; }\n maxP { type fieldMinMax; }\n}\n'
    graph=sources.prepare_sources(corpus(tmp_path,{'tutorials/blastFoam/case/constant/phaseProperties':text}))
    selected=[n for n in graph['nodes'].values() if n.get('key')=='equationOfState']
    assert len(selected)==2 and selected[0]['owner']!=selected[1]['owner']
    objects=[n for n in graph['nodes'].values() if n.get('key')=='type']
    assert len(objects)==2 and objects[0]['owner']!=objects[1]['owner']
    for node in graph['nodes'].values():
        unit=graph['units'][node['unit_id']]
        assert node['owner']==unit['owner']
        assert all(unit['start']<=a['start']<=a['end']<=unit['end'] for a in node['evidence'])

def test_partition_has_no_missing_or_duplicated_lines_and_long_units_keep_owner(tmp_path):
    text='# Header\n'+('long source line\n'*15)+'## Other\nlast\n'
    graph=sources.prepare_sources(corpus(tmp_path,{'manual/markdown/file.md':text}),max_chars=80)
    units=list(graph['units'].values());numbers=[n for u in units for n in range(u['start'],u['end']+1)]
    assert sorted(numbers)==list(range(1,len(text.splitlines())+1))
    assert len(set(numbers))==len(numbers)
    first=[u for u in units if u['owner_key']=='heading:1']
    assert len(first)>1 and len({u['owner'] for u in first})==1

def test_scripts_are_not_interpreted_as_foam_dictionaries(tmp_path):
    text='#!/bin/sh\nrunApplication blastFoam\nfunction task() { echo hello; }\n'
    graph=sources.prepare_sources(corpus(tmp_path,{'tutorials/blastFoam/case/Allrun':text}))
    assert all(n['kind']=='original_unit' for n in graph['nodes'].values())
    assert graph['semantic_plans']=={}

def test_long_literal_never_indexes_a_value_outside_its_evidence(tmp_path):
    text='FoamFile { format ascii; }\nvalues\n(\n'+('12345\n'*30)+');\n'
    graph=sources.prepare_sources(corpus(tmp_path,{'tutorials/blastFoam/case/constant/list':text}),max_chars=80)
    node=next(n for n in graph['nodes'].values() if n.get('key')=='values')
    assert node['value']==''
    assert 'literal_spans_source_fragment_not_indexed_as_value' in node['flags']
