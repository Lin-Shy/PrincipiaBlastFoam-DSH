"""跨来源边需要模型、键、物理作用域及两侧原文，不靠全局同名。"""
from pathlib import Path
import sys
import shutil

import pytest

SKILL=Path(__file__).resolve().parents[1]/'.dsh/skills/blastfoam-knowledge'
sys.path.insert(0,str(SKILL/'scripts'))
import knowledge as k
import task_structure as t
import task_evidence as b


@pytest.fixture
def skill(tmp_path):
    root=tmp_path/'skill'
    shutil.copytree(SKILL/'scripts',root/'scripts',ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copytree(SKILL/'references',root/'references')
    sources={
        'manual/markdown/01_models.md':'''# Models

## 1.1 Thermodynamic models

### 1.1.1 twin

| Variable | Description |
|---|---|
| heat | Heat input [K] |

## 1.2 Fluid Transport

### 1.2.1 twin

| Variable | Description |
|---|---|
| coeff | Transport coefficient (7 by default if active) [Pa] |
| $T_s$ | Temperature [K] |

### 1.2.2 distinct

| Variable | Description |
|---|---|
| coeff | Other coefficient [Pa] |
''',
        'tutorials/sample/Allrun':'runApplication blockMesh\n',
        'tutorials/sample/system/controlDict':'FoamFile {class dictionary;}\napplication blastFoam;\n',
        'tutorials/sample/constant/phaseProperties':'''FoamFile {class dictionary;}
left
{
 thermoType { transport twin; thermo twin; }
 transport { coeff 10; Ts 20; }
 thermodynamics { heat 30; }
}
right
{
 thermoType { transport distinct; }
 transport { coeff 40; }
}
name twin;
''',
        'tutorials/included/Allrun':'runApplication blockMesh\n',
        'tutorials/included/system/controlDict':'FoamFile {class dictionary;}\napplication blastFoam;\n',
        'tutorials/included/constant/phaseProperties':'FoamFile {class dictionary;}\nthermoType { transport twin; }\n#include "fragment"\n',
        'tutorials/included/constant/fragment':'speciesA { transport { coeff 60; Ts 70; } }\n',
    }
    for name,text in sources.items():
        path=root/'corpus'/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text)
    k.build(root,parse_included_dictionaries=True)
    return root


def aligned(graph):return [e for e in graph['edges'] if e['relation'].startswith('PARAMETER_INSTANCE')]


def test_numbered_homonyms_are_disambiguated_by_selector_family(skill):
    graph,_,_=t.augment(skill,'aligned')
    nodes={n['id']:n for n in graph['nodes']}; edges=aligned(graph)
    assert edges
    for edge in edges:
        instance,param,selector=(nodes[edge[n]] for n in ('source','target','selector'))
        if instance['key']=='heat':assert 'Thermodynamic models' in param['hierarchy'][1]
        elif instance['key']=='coeff':assert 'Fluid Transport' in param['hierarchy'][1]
        assert instance['scope']['components'][0]==selector['scope']['components'][0]
        assert instance['instance_value']!=param.get('default_statements')
        assert not instance['is_general_default']
    assert not any(nodes[e['selector']]['key']=='name' for e in edges)
    assert not any(nodes[e['source']]['key']=='Ts' for e in edges)
    assert not any('fragment' in e['source'] for e in edges)


def test_notation_and_include_links_remain_explicit_candidates(skill):
    graph,_,_=t.augment(skill,'candidates'); nodes={n['id']:n for n in graph['nodes']}
    candidates=[e for e in aligned(graph) if e['relation']=='PARAMETER_INSTANCE_CANDIDATE']
    assert any(nodes[e['source']]['key']=='Ts' for e in candidates)
    assert any('fragment' in e['source'] for e in candidates)
    for edge in candidates:
        assert edge['status']=='scoped_candidate_needs_source_check'
        assert {ev['path'].split('/')[0] for ev in edge['supporting_evidence']}=={'manual','tutorials'}
    assert not any('sample/constant/phaseProperties:right' in e['source'] and nodes[e['target']]['evidence']['section'].endswith('twin') for e in aligned(graph))


def test_global_name_uniqueness_and_case_folding_do_not_prove_factory_identity(skill):
    path=skill/'corpus/tutorials/sample/constant/phaseProperties'
    path.write_text(path.read_text()+'''\nunknown { type distinct; coeff 90; }
boundaryField { left { type distinct; coeff 91; } }
wrongCase { thermoType { transport DISTINCT; } transport { coeff 92; } }
''')
    k.build(skill,parse_included_dictionaries=True)
    graph,_,_=t.augment(skill,'candidates');nodes={n['id']:n for n in graph['nodes']}
    assert not any(nodes[e['source']]['dictionary_path'].startswith(('unknown/','boundaryField/','wrongCase/')) for e in aligned(graph))
    assert any(i['reason']=='selector_factory_scope_not_established' for i in graph['task_structure']['issues'])


def test_shared_owner_parameter_is_cooccurrence_not_deterministic_ownership(skill):
    manual=skill/'corpus/manual/markdown/01_models.md'
    manual.write_text(manual.read_text()+'''\n## 1.3 Frictional stress models

### 1.3.1 friction

| Variable | Description |
|---|---|
| coeff | Shared named coefficient |

## 1.4 Packing limit models

### 1.4.1 packing

| Variable | Description |
|---|---|
| coeff | Shared named coefficient |
''')
    path=skill/'corpus/tutorials/sample/constant/phaseProperties'
    path.write_text(path.read_text()+'''\nkineticTheory { frictionalStressModel friction; packingLimitModel packing;
 coeff 1; frictionCoeffs { coeff 2; } }
''')
    k.build(skill,parse_included_dictionaries=True)
    graph,_,_=t.augment(skill,'candidates');nodes={n['id']:n for n in graph['nodes']}
    shared=[e for e in aligned(graph) if nodes[e['source']]['dictionary_path']=='kineticTheory/coeff']
    assert len(shared)==2
    assert all(e['relation']=='PARAMETER_INSTANCE_CANDIDATE' and 'shared_block_parameter_ownership_unresolved' in e['candidate_reasons'] for e in shared)
    named=[e for e in aligned(graph) if nodes[e['source']]['dictionary_path']=='kineticTheory/frictionCoeffs/coeff']
    assert len(named)==1 and named[0]['relation']=='PARAMETER_INSTANCE'


def test_parameter_granularity_and_alignment_are_separate_factors(skill):
    off,_,_=t.augment(skill,'off'); nodes,_,_=t.augment(skill,'nodes')
    assert not any(n['kind']=='manual_parameter' for n in off['nodes'])
    assert sum(n['kind']=='manual_parameter' for n in nodes['nodes'])==4
    assert not aligned(off) and not aligned(nodes)
    assert not any(e['relation']=='SELECTS_DOCUMENTED_MODEL' for e in nodes['edges'])
    assert nodes==t.augment(skill,'nodes')[0]


def test_include_scope_and_duplicate_selector_fail_closed(skill):
    contexts=t.directive_contexts('block {\n#include "one"\n}\n#if 1\n#include "two"\n#endif\n#include "three"\n')
    assert contexts[2]['components']==['block']
    assert not contexts[5]['resolved_scope']
    assert contexts[7]['resolved_scope']
    path=skill/'corpus/tutorials/included/constant/phaseProperties'
    path.write_text(path.read_text().replace('transport twin;','transport twin; transport distinct;'))
    k.build(skill,parse_included_dictionaries=True)
    graph,_,_=t.augment(skill,'candidates')
    assert not any('tutorials/included/' in e['source'] for e in aligned(graph))
    assert any(i['reason']=='duplicate_selector_needs_override_resolution' for i in graph['issues'])


def test_projection_preserves_parent_evidence_and_catches_source_edits(skill):
    t.build(skill,'candidates')
    engine=b.EvidenceSearch(skill=skill)
    domain=b.domain(engine)
    assert domain['coverage']['parameter_rows']==4
    assert any(e['relation']=='PARAMETER_INSTANCE_CANDIDATE' for e in engine.graph['edges'])
    assert any(e.get('structural_relation')=='PARAMETER_CONTEXT' and e['relation']=='SECTION_CONTEXT' for e in engine.graph['edges'])
    source=skill/'corpus/tutorials/included/constant/fragment'
    source.write_text(source.read_text().replace('60','61'))
    with pytest.raises(ValueError,match='corpus changed'):engine.validate()
