import shutil
import pytest
from principia_core.dictionary_edits import apply_dictionary_edits

pytestmark=pytest.mark.skipif(shutil.which('foamDictionary') is None,reason='OpenFOAM required')


def fixture(tmp_path):
    (tmp_path/'system').mkdir()
    p=tmp_path/'system/fvSolution'
    p.write_text('FoamFile {format ascii; class dictionary; object fvSolution;}\nsolvers { "(U|e)" { solver diagonal; } }\n')
    return p


def test_literal_parent_does_not_mutate_regex_fallback(tmp_path):
    from principia_core.dictionary_edits import _run
    p=fixture(tmp_path)
    result=apply_dictionary_edits(tmp_path,[{'path':'system/fvSolution','entry':'solvers/U/solver','value':'PBiCGStab'},
         {'path':'constant/momentumTransport','entry':'simulationType','value':'laminar'}])
    assert result['status']=='applied'
    assert _run(p,'-entry','solvers/U/solver','-value').strip()=='PBiCGStab'
    assert _run(p,'-entry','solvers/(U|e)/solver','-value').strip()=='diagonal'


def test_failure_and_dry_run_leave_original_files_unchanged(tmp_path):
    p=fixture(tmp_path);before=p.read_bytes()
    edits=[{'path':'system/fvSolution','entry':'solvers/(U|e)/solver','value':'PBiCGStab'}]
    assert apply_dictionary_edits(tmp_path,edits,dry_run=True)['status']=='validated'
    assert p.read_bytes()==before
    with pytest.raises(ValueError):apply_dictionary_edits(tmp_path,edits+[{'path':'system/fvSolution','entry':'missing','value':None}])
    assert p.read_bytes()==before
    with pytest.raises(ValueError):apply_dictionary_edits(tmp_path,[{'path':'../outside','entry':'x','value':'1'}])


def test_values_cannot_insert_unrequested_sibling_keys(tmp_path):
    p=fixture(tmp_path);before=p.read_bytes()
    with pytest.raises(ValueError,match='sibling'):
        apply_dictionary_edits(tmp_path,[{'path':'system/fvSolution','entry':'x','value':'1; other 2'}])
    assert p.read_bytes()==before


def test_explicit_group_edit_and_remove(tmp_path):
    from principia_core.dictionary_edits import _run
    p=fixture(tmp_path)
    apply_dictionary_edits(tmp_path,[{'path':'system/fvSolution','entry':'solvers/(U|e)/solver','value':'PBiCGStab'}])
    assert _run(p,'-entry','solvers/(U|e)/solver','-value').strip()=='PBiCGStab'
    apply_dictionary_edits(tmp_path,[{'path':'system/fvSolution','entry':'solvers/(U|e)','value':None}])
    assert '(U|e)' not in p.read_text()


def test_group_feedback_detects_actual_shadowing_without_publishing_dry_run(tmp_path):
    p=fixture(tmp_path)
    p.write_text(p.read_text().replace('} }', '} ".*" { solver diagonal; } }'))
    before=p.read_bytes()
    edits=[{'path':'system/fvSolution','entry':'solvers/(U|e)/solver','value':'PBiCGStab'}]
    result=apply_dictionary_edits(tmp_path,edits,dry_run=True)
    assert p.read_bytes()==before
    feedback=result['effective_lookups']
    assert feedback['has_mismatch']
    assert {c['lookup_entry'] for c in feedback['checks']}=={'solvers/U/solver','solvers/e/solver'}
    assert all(c['effective_value']=='diagonal' for c in feedback['checks'])
    assert all(c['group_value']=='PBiCGStab' for c in feedback['checks'])
    # Exact overrides win even in the presence of the later catch-all pattern.
    edits += [{'path':'system/fvSolution','entry':f'solvers/{name}/solver','value':'PBiCGStab'} for name in ('U','e')]
    assert not apply_dictionary_edits(tmp_path,edits)['effective_lookups']['has_mismatch']


def test_group_feedback_uses_final_state_and_reports_bounded_scope(tmp_path):
    fixture(tmp_path)
    edits=[{'path':'system/fvSolution','entry':'solvers/(U|e)/solver','value':'PBiCGStab'},
           {'path':'system/fvSolution','entry':'solvers/(U|e)/solver','value':'PCG'}]
    checks=apply_dictionary_edits(tmp_path,edits)['effective_lookups']['checks']
    assert len(checks)==2
    assert all(c['group_value']=='PCG' and c['matches_group'] for c in checks)


def test_literal_edits_do_not_claim_group_lookup_validation(tmp_path):
    fixture(tmp_path)
    r=apply_dictionary_edits(tmp_path,[{'path':'system/fvSolution','entry':'solvers/U/solver','value':'PBiCGStab'}])
    assert r['status']=='applied'
    feedback=r['effective_lookups']
    assert feedback['status']=='not_checked'
    assert feedback['has_mismatch'] is None
    assert feedback['checks']==[] and feedback['checked_lookups']==0


def test_failed_lookup_is_unknown_not_a_pass(tmp_path,monkeypatch):
    from principia_core import dictionary_edits as module
    fixture(tmp_path)
    def fail(*args):raise ValueError('resolver unavailable')
    monkeypatch.setattr(module,'_run',fail)
    r=module._effective_group_lookups(tmp_path,[('system/fvSolution','solvers/(U|e)/solver','PCG')])
    assert r['status']=='partial' and r['has_mismatch'] is None
    assert r['checked_lookups']==0


def test_lookup_cap_does_not_claim_complete_validation(tmp_path):
    from principia_core.dictionary_edits import _effective_group_lookups
    p=fixture(tmp_path);names='|'.join('v'+str(i) for i in range(34))
    p.write_text('FoamFile {format ascii; class dictionary; object fvSolution;}\nsolvers { "('+names+')" { solver PCG; } }')
    r=_effective_group_lookups(tmp_path,[('system/fvSolution','solvers/('+names+')/solver','PCG')])
    assert r['limited'] and r['status']=='partial' and r['has_mismatch'] is None
    assert r['checked_lookups']==32
