import sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments/retrieval_method'))
import candidate_semantics as sem


def test_chunks_cover_every_primary_line_without_gaps():
    lines=['# Parent']+[f'line {i} '+ 'x'*40 for i in range(1,40)]
    chunks=list(sem.chunks('manual.md','\n'.join(lines),max_chars=240))
    assert [n for c in chunks for n in range(c['primary_start'],c['end']+1)]==list(range(1,len(lines)+1))
    assert chunks[-1]['heading_context'][0]['line']==1
    assert all(c['start']<=c['primary_start']<=c['end'] for c in chunks)


def test_source_evidence_cannot_use_unseen_lines_or_forged_quote():
    lines=['# Role','visible','unseen']
    chunk={'path':'manual.md','start':2,'end':2,'heading_context':[{'line':1}]}
    assert sem.validate_span({'start':1,'end':1,'quote':'Role'},chunk,lines)['path']=='manual.md'
    with pytest.raises(ValueError,match='outside'):
        sem.validate_span({'start':3,'end':3,'quote':'unseen'},chunk,lines)
    with pytest.raises(ValueError,match='mismatch'):
        sem.validate_span({'start':2,'end':2,'quote':'invented'},chunk,lines)


def test_requires_without_explicit_condition_is_rejected():
    chunk={'path':'manual.md','start':1,'end':1,'heading_context':[]}
    row={'subject':'a','subject_role':'model','predicate':'REQUIRES_WHEN','object':'b','condition':None,
         'status':'document_rule','evidence':[{'start':1,'end':1,'quote':'a b'}]}
    value=sem.validate_extraction({'definitions':[],'assertions':[row]},chunk,['a b'])
    assert not value['assertions']
    assert len(value['rejected'])==1


def test_verifier_preserved_indices_are_not_mistaken_for_missing_votes():
    items=[{'extraction_index':0},{'extraction_index':2},{'extraction_index':4}]
    lookup=sem.verifier_lookup(items,[{'index':i} for i in [0,2,4]])
    assert lookup[4] is items[2]
    compact=sem.verifier_lookup(items,[{'index':i} for i in [0,1,2]])
    assert compact[2] is items[2]
    with pytest.raises(ValueError,match='coverage'):
        sem.verifier_lookup(items,[{'index':0},{'index':0},{'index':4}])
