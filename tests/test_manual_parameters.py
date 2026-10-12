"""参数表来自文档结构，不可通过默认词或符号规范化制造跨模型事实。"""
from pathlib import Path
import sys

SCRIPTS=Path(__file__).resolve().parents[1]/'.dsh/skills/blastfoam-knowledge/scripts'
sys.path.insert(0,str(SCRIPTS))
import manual_graph
import manual_parameters as p


def test_table_rows_preserve_source_and_owning_model(tmp_path):
    raw='''# Models

## first

| Variable | Description |
|---|---|
| value | Reference value (0 by default for gas) [Pa] |
| $A_s$ | Model coefficient [kg/m/s/K^1/2] |

## second

| Entry | Description |
|---|---|
| value | Required only if active [K] |
| `radii` (`radius`) | Input radii (default is 1) [m] |
'''
    (tmp_path/'01_models.md').write_text(raw)
    graph=p.build(manual_graph.build(tmp_path))
    assert graph['counts']['parameters']==4
    first,coefficient,second,radii=graph['nodes']
    assert first['section']!=second['section']
    assert first['default_statements']==['0 by default for gas']
    assert first['conditional_text'].endswith('[Pa]')
    assert second['default_status']=='not_stated_in_this_row'
    assert second['requirement_statements']==['Required only if active [K]']
    assert coefficient['identifiers']==[{'name':'As','status':'notation_normalization_candidate'}]
    assert {n['name'] for n in radii['identifiers']}=={'radii','radius'}
    for n in graph['nodes']:
        assert raw.splitlines()[n['evidence']['line_start']-1]==n['raw_row']
        assert n['evidence']['sha256']==p.sha(raw)
    assert graph['llm_calls']==0


def test_other_tables_and_complex_notation_are_not_fabricated(tmp_path):
    (tmp_path/'01_models.md').write_text('# Models\n\n| Model | Description |\n|---|---|\n| m | Is a model |\n')
    graph=p.build(manual_graph.build(tmp_path))
    assert not graph['nodes']
    assert not p.identifiers(r'$\\frac{a}{b}$')
    assert not p.identifiers('coefficient with unspecified name')
    assert p.qualifiers('Reference temperature [K]')['default_status']=='not_stated_in_this_row'


def test_table_change_updates_identity_and_no_default_inheritance(tmp_path):
    path=tmp_path/'01_models.md'
    path.write_text('# Root\n\nDefaults in this section are conditional.\n\n## Model\n\n| Variable | Description |\n|---|---|\n| x | Value [K] |\n')
    first=p.build(manual_graph.build(tmp_path))
    assert first['nodes'][0]['default_statements']==[]
    assert first==p.build(manual_graph.build(tmp_path))
    path.write_text(path.read_text().replace('Value [K]','Value (default is 7) [K]'))
    second=p.build(manual_graph.build(tmp_path))
    assert first['snapshot']!=second['snapshot']
    assert second['nodes'][0]['default_statements']==['default is 7']


def test_explicit_default_columns_and_invalid_separator(tmp_path):
    path=tmp_path/'01_models.md'
    path.write_text('# Model\n\n| Entry | Description | Default | Required |\n|---|---|---|---|\n| name | Name | none | no |\n| value | Value | - | if active |\n')
    graph=p.build(manual_graph.build(tmp_path))
    assert graph['nodes'][0]['default_statements']==['Default: none']
    assert graph['nodes'][1]['default_status']=='not_stated_in_this_row'
    assert graph['nodes'][1]['requirement_statements']==['Required: if active']
    assert not p.identifiers('$T_{ref$')
    path.write_text(path.read_text().replace('|---|---|---|---|','|broken|header|not|separator|'))
    graph=p.build(manual_graph.build(tmp_path))
    assert not graph['nodes']
    assert graph['issues'][0]['reason']=='parameter_table_separator_invalid'
