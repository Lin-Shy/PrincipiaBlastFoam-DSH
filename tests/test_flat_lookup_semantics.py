import json
import pytest
from tests.test_lookup_semantics import fixture
from experiments.retrieval_method.lookup_semantics import LookupSemantics
from experiments.retrieval_method.flat_lookup_semantics import FlatLookupSemantics,materialize


def flat(path):
    record=materialize(LookupSemantics(path));target=path.with_name('flat.json')
    target.write_text(json.dumps(record));return FlatLookupSemantics(target)


def test_same_evidence_and_no_runtime_topology(fixture):
    path,g,p,save=fixture;a=LookupSemantics(path);b=flat(path)
    assert b.reference(p)==a.reference(p)
    assert b.rule_text()==a.rule_text()
    assert b.read_file('source.C')==a.read_file('source.C')
    assert 'nodes' not in b.record and 'edges' not in b.record
    path.unlink()
    assert b.reference(p) is not None  # Runtime does not access source graph.


def test_recompile_disconnected_chain_and_wrong_context(fixture):
    path,g,p,save=fixture
    p['condition_snapshot']='wrong';assert flat(path).reference(p) is None
    p['condition_snapshot']='bound';g['edges']=[];save()
    assert flat(path).reference(p) is None


def test_materialized_sources_still_fail_closed(fixture):
    path,g,p,save=fixture;b=flat(path)
    (path.parent/'source.C').write_text('changed')
    with pytest.raises(ValueError,match='source changed'):b.read_file('source.C')
    with pytest.raises(ValueError,match='source changed'):FlatLookupSemantics(path.with_name('flat.json'))
