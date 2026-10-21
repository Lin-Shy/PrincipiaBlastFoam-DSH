"""The semantic alias compiler cannot move an alias away from its source."""
from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'experiments/retrieval_method'))
from chapter2_compile_graph_aliases import attach, verified_rows


def source():
    unit = dict(id='u', kind='markdown_section', path='manual/a.md', start=1, end=2,
        text='# Pressure\nPressure equation', sha256='a'*64)
    graph = dict(units={'u': unit}, nodes={'n':dict(id='n', kind='original_unit', unit_id='u',
        path=unit['path'], owner='source-u', aliases=[])}, edges=[])
    task = dict(path=unit['path'], units=[dict(unit_id='u', **{k:unit[k] for k in ('path','start','end','text')})])
    row = dict(unit_id='u', aliases=['压力方程'], quote='Pressure equation')
    return graph, [task], [row]


def test_alias_changes_only_owning_raw_node_and_preserves_original_graph():
    graph, tasks, rows = source(); before = deepcopy(graph)
    revised, stats = attach(graph, tasks, rows)
    assert graph == before
    assert revised['units'] == graph['units'] and revised['edges'] == graph['edges']
    assert revised['nodes']['n']['aliases'] == ['压力方程']
    assert revised['nodes']['n']['alias_grounding'][0]['source_sha256'] == 'a'*64
    assert stats['source_units_with_aliases'] == 1


@pytest.mark.parametrize('drift', ['quote', 'unit', 'source', 'duplicate'])
def test_alias_rejects_unowned_quote_or_changed_source(drift):
    graph, tasks, rows = source()
    if drift == 'quote': rows[0]['quote'] = 'Unstated recommendation'
    if drift == 'unit': rows[0]['unit_id'] = 'other'
    if drift == 'source': tasks[0]['units'][0]['text'] += ' changed'
    if drift == 'duplicate': tasks.append(deepcopy(tasks[0]))
    with pytest.raises(ValueError): attach(graph, tasks, rows)


def test_unaccepted_batch_is_never_compiled_as_verified(tmp_path):
    # A failed proposer without a two-stage accepted artifact is retained,
    # rather than converted into a verified batch or automatically replayed.
    (tmp_path/'propose.json').write_text(json.dumps(dict(status='failed')), encoding='utf-8')
    rows, binding = verified_rows({}, 0, tmp_path)
    assert rows == [] and binding['status'] == 'not_accepted'
