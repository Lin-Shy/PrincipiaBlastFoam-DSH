import json

import pytest

from experiments.retrieval_method.navigation_review import merge_reviews


def test_review_merge_preserves_identity_and_rejects_duplicate_sessions(tmp_path):
    row={'session':'Qx--no_graph--r1',**{k:'frozen-hash' for k in ('answer_sha256','trace_sha256','annotation_sha256','packet_sha256','authored_decisions_sha256')}}
    first=tmp_path/'first.json';first.write_text(json.dumps([row]))
    second=tmp_path/'second.json';second.write_text(json.dumps([{**row,'session':'Qy--graph_first--r1'}]))
    out=tmp_path/'merged.json'
    merge_reviews([first,second],out)
    assert json.loads(out.read_text())==[row,{**row,'session':'Qy--graph_first--r1'}]
    with pytest.raises(ValueError,match='duplicate review'):
        merge_reviews([first,first],tmp_path/'duplicate.json')
    with pytest.raises(ValueError,match='preserve previous'):
        merge_reviews([first],out)


def test_review_merge_requires_compiled_provenance(tmp_path):
    path=tmp_path/'authored.json';path.write_text(json.dumps([{'session':'Qx'}]))
    with pytest.raises(ValueError,match='identity-bound'):
        merge_reviews([path],tmp_path/'out.json')
