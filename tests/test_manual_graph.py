"""章节重建、证据完整性、条件出处及预算的可观察不变量。"""
import copy
import json
from pathlib import Path
import sys

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]/'.dsh/skills/blastfoam-knowledge/scripts'
sys.path.insert(0, str(SCRIPTS))
import manual_graph as g
import manual_semantic as sem
from manual_search import ManualSearch


@pytest.fixture
def source(tmp_path):
    (tmp_path/'01_models.md').write_text('''# Models

General conditions apply only when stated.

## 1.1 alpha

The pressure is given by

$$
p = \\rho e
$$
(1.1)

where $e$ is internal energy.

> **NOTE:** alpha works only for fluids.

| Variable | Description |
|---|---|
| $e$ | Energy |

```cpp
# This is a code comment, not a heading
value alpha;
```

## 1.2 beta

See 1.1 for alpha.
''')
    return tmp_path


def test_lossless_structure_and_formula_explanation_are_bound(source):
    graph = g.build(source); report = g.validate(graph, source)
    assert report['counts']['section'] == 3
    assert report['blocks']['formula'] == 1
    assert report['formula_numbers'] == 1
    alpha = next(n for n in graph['nodes'] if n['kind'] == 'evidence' and 'where' in n['markdown'])
    assert '(1.1)' in alpha['markdown'] and '**NOTE:**' in alpha['markdown']
    assert 'table' in alpha['block_kinds'] and 'code' in alpha['block_kinds']
    assert any(e['relation'] == 'REFERS_TO_SECTION' for e in graph['edges'])
    sections = [n for n in graph['nodes'] if n['kind'] == 'section']
    assert sections[0]['end'] < sections[0]['subtree_end']
    assert g.build(source) == graph


def test_source_change_and_tampering_are_rejected(source):
    graph = g.build(source)
    damaged = copy.deepcopy(graph)
    next(n for n in damaged['nodes'] if n['kind'] == 'evidence')['markdown'] = 'invented'
    with pytest.raises(ValueError, match='snapshot'):
        g.validate(damaged, source)
    (source/'01_models.md').write_text('# Changed\n')
    with pytest.raises(ValueError, match='sources changed'):
        g.validate(graph, source)


@pytest.mark.parametrize('text', ['# X\n\n$$\nx=1\n', '# X\n\n```cpp\nx=1\n'])
def test_unclosed_atomic_content_fails_before_publishing(tmp_path, text):
    (tmp_path/'x.md').write_text(text)
    with pytest.raises(ValueError, match='unclosed'):
        g.build(tmp_path)


def test_oversized_formula_is_whole_or_omitted(tmp_path):
    (tmp_path/'x.md').write_text('# Formula\n\nPressure formula\n\n$$\np='+('x+'*4000)+'1\n$$\n(1.1)\n\nwhere x is given.\n')
    graph = g.build(tmp_path)
    engine = ManualSearch(graph)
    small = engine.search('Pressure formula', budget=1000)
    assert small['selected'] == [] and small['omitted']
    large = engine.search('Pressure formula', budget=12000)
    assert 'where x is given.' in large['markdown'] and len(large['selected']) == 1


def test_images_cannot_escape_source_root(tmp_path):
    root = tmp_path/'source'; root.mkdir()
    (tmp_path/'external.png').write_bytes(b'not read')
    (root/'x.md').write_text('# X\n\n![image](../external.png)\n')
    with pytest.raises(ValueError, match='image source'):
        g.build(root)


def response_fixture(graph):
    plan = sem.make_plan(graph, chapter='01_models.md')
    unit = plan['batches'][0]
    alpha = next(s for s in plan['catalog'] if s['label'] == '1.1 alpha')['id']
    source = next(s for s in unit['sources'] if s['section'] == alpha and '**NOTE:**' in s['text'])
    fact = {'subject': {'name': 'alpha', 'kind': 'model', 'scope': alpha},
            'object': {'name': 'fluids', 'kind': 'concept', 'scope': alpha},
            'relation': 'LIMITED_TO', 'summary_zh': 'alpha仅用于流体', 'conditions_zh': 'only for fluids',
            'anchors': [{'source': source['id'], 'quote': 'alpha works only for fluids.'}]}
    payload = {'sections': [{'id': sid, 'summary_zh': '', 'deferred': [], 'facts': [fact] if sid == alpha else []}
                            for sid in unit['target_sections']]}
    response = {'raw_response': {'model': 'deepseek-flash', 'choices': [{'finish_reason': 'stop',
                  'message': {'content': json.dumps(payload)}}]}}
    return plan, unit, payload, response


def test_semantic_exact_quotes_target_scope_and_raw_symbols(source):
    plan, unit, payload, response = response_fixture(g.build(source))
    accepted, rejected, coverage = sem.validate_payload(plan, unit, response)
    assert len(accepted) == 1 and not rejected and len(coverage) == 3
    assert accepted[0]['conditions_zh'] == 'only for fluids'
    fact = next(s for s in payload['sections'] if s['facts'])['facts'][0]
    fact['anchors'][0]['quote'] = 'alpha always works'
    response['raw_response']['choices'][0]['message']['content'] = json.dumps(payload)
    accepted, rejected, _ = sem.validate_payload(plan, unit, response)
    assert not accepted and rejected


def test_semantic_batch_coverage_and_model_mismatch_block_acceptance(source):
    plan, unit, payload, response = response_fixture(g.build(source))
    response['raw_response']['model'] = 'other-model'
    with pytest.raises(ValueError, match='model mismatch'):
        sem.validate_payload(plan, unit, response)
    response['raw_response']['model'] = 'deepseek-flash'
    payload['sections'].pop()
    response['raw_response']['choices'][0]['message']['content'] = json.dumps(payload)
    with pytest.raises(ValueError, match='coverage'):
        sem.validate_payload(plan, unit, response)


def test_exact_flash_model_is_frozen_in_plan_and_response_identity(source):
    graph = g.build(source)
    plan, unit, _, response = response_fixture(graph)
    assert plan['extraction']['model'] == 'deepseek-flash'
    with pytest.raises(ValueError, match='unsupported extraction model'):
        sem.make_plan(graph, chapter='01_models.md', model='legacy-alias')
    response['raw_response']['model'] = 'other-model'
    with pytest.raises(ValueError, match='model mismatch'):
        sem.validate_payload(plan, unit, response)
    response['raw_response']['model'] = 'deepseek-flash'
    facts, rejected, _ = sem.validate_payload(plan, unit, response)
    assert len(facts) == 1 and not rejected


def test_global_catalog_does_not_expand_extraction_targets(source):
    (source/'02_other.md').write_text('# 2 Other\n\nA separate topic.\n')
    graph = g.build(source)
    local = sem.make_plan(graph, chapter='01_models.md')
    global_plan = sem.make_plan(graph, chapter='01_models.md', global_catalog=True)
    assert len(global_plan['catalog']) > len(local['catalog'])
    assert [u['target_sections'] for u in global_plan['batches']] == [u['target_sections'] for u in local['batches']]
    assert global_plan['snapshot'] != local['snapshot']


def test_unrecognized_extraction_model_is_rejected(source):
    with pytest.raises(ValueError, match='unsupported extraction model'):
        sem.make_plan(g.build(source), chapter='01_models.md', model='unspecified-alias')


@pytest.mark.parametrize('strategy', ['text', 'sections', 'semantic'])
def test_common_budget_exact_evidence_and_no_duplicates(source, strategy):
    graph = g.build(source)
    plan, unit, _, response = response_fixture(graph)
    facts, _, _ = sem.validate_payload(plan, unit, response)
    semantic = {'foundation_snapshot': graph['snapshot'], 'snapshot': 'test', 'facts': facts}
    packet = ManualSearch(graph, semantic).search('alpha fluids', strategy, 1200)
    assert len(packet['markdown']) <= 1200
    assert len({n['unit'] for n in packet['selected']}) == len(packet['selected'])
    for selected in packet['selected']:
        node = next(n for n in graph['nodes'] if n['id'] == selected['unit'])
        assert node['markdown'] in packet['markdown']


def test_rejected_relation_cannot_be_used_for_expansion(source):
    graph = g.build(source)
    plan, unit, _, response = response_fixture(graph)
    facts, _, _ = sem.validate_payload(plan, unit, response)
    semantic = {'foundation_snapshot': graph['snapshot'], 'snapshot': 'test', 'facts': facts}
    review = {'semantic_snapshot': 'test', 'decisions': [{'fact': facts[0]['id'], 'status': 'reject'}]}
    assert not ManualSearch(graph, semantic, review).facts


def test_explicit_references_skip_code_math_and_years(source):
    p = source/'01_models.md'
    p.write_text(p.read_text()+'''\nSee Sections 1.1 and 2. Eq. (1.1). Equations 2012.
`Sec. 99` and $\\text{Section 98}$ are literal examples.

```text
See Sec. 97.
```

$$
\\text{Section 96}
$$
''')
    (source/'02_next.md').write_text('# Next\n\nSecond chapter.\n')
    graph = g.build(source); ns = {n['id']:n for n in graph['nodes']}
    links = [e for e in graph['edges'] if e['relation'].startswith('REFERS_TO')]
    assert any(e['relation']=='REFERS_TO_FORMULA' for e in links)
    assert {ns[e['target']].get('number') for e in links if e['relation']=='REFERS_TO_SECTION'} == {'1.1','2'}
    assert not graph['warnings']
    for e in links:
        assert e['quote'] in ns[e['source']]['markdown']


def test_extensions_cannot_displace_named_lexical_matches(tmp_path):
    (tmp_path/'01_models.md').write_text('# Models\n\n## 1.1 amber\n\namber setting.\n\n## 1.2 cobalt\n\ncobalt default setting.\n\n## 1.3 context\n\n'+('context '*85)+'\n')
    graph = g.build(tmp_path); engine = ManualSearch(graph, {'foundation_snapshot':graph['snapshot'],'snapshot':'fixture','facts':[]})
    units = {n['label'].split(' · ')[0]:n['id'] for n in graph['nodes'] if n['kind']=='evidence'}
    engine.expand_semantic = lambda *args: [(units['1.3 context'], {'relation':'fixture'})]
    baseline = engine.search('amber cobalt', 'text', 1100)
    actual = engine.search('amber cobalt', 'semantic', 1100)
    assert {u['unit'] for u in baseline['selected']} <= {u['unit'] for u in actual['selected']}
    assert set(actual['protected_lexical']) <= {u['unit'] for u in actual['selected']}
    assert actual['characters'] <= 1100


def test_semantic_rebase_rejects_changed_evidence(source):
    from rebase_manual_semantic import rebase
    old = g.build(source); new = copy.deepcopy(old)
    semantic = {'foundation_snapshot':old['snapshot'],'facts':[]}
    semantic['snapshot'] = g.sha(g.encoded(semantic))
    review = {'semantic_snapshot':semantic['snapshot'],'decisions':[]}
    new['edges'].append({'source':old['nodes'][0]['id'],'target':old['nodes'][1]['id'],'relation':'REFERS_TO_SECTION'})
    new['snapshot'] = g.sha(g.encoded({k:v for k,v in new.items() if k!='snapshot'}))
    result, reviewed = rebase(old, new, semantic, review)
    assert result['facts']==semantic['facts'] and reviewed['decisions']==review['decisions']
    next(n for n in new['nodes'] if n['kind']=='evidence')['markdown']='changed'
    new['snapshot'] = g.sha(g.encoded({k:v for k,v in new.items() if k!='snapshot'}))
    with pytest.raises(ValueError,match='sources or nodes changed'):
        rebase(old,new,semantic,review)


def test_unique_query_cue_in_baseline_is_protected(tmp_path):
    (tmp_path/'01_models.md').write_text('# General guide\n\n## 1.1 First topic\n\ncommon '+ 'background '*16 +
        '\n\n## 1.2 Other topic\n\ncommon uniquelynamed '+ 'background '*5 +'\n')
    graph = g.build(tmp_path); engine = ManualSearch(graph)
    ranked = [(2-i,n['id']) for i,n in enumerate(n for n in graph['nodes'] if n['kind']=='evidence')]
    engine.ranked = lambda query: ranked
    baseline = engine.search('common uniquelynamed', budget=500)
    assert sum(len(engine.chunk(u,1)) for _,u in ranked)>300
    protected = engine.protected_lexical('common uniquelynamed',ranked,500)
    unique = next(n['id'] for n in graph['nodes'] if n['kind']=='evidence' and 'uniquelynamed' in n['markdown'])
    assert unique in {s['unit'] for s in baseline['selected']}
    assert unique in protected
