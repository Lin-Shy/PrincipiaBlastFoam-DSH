"""Failure-injection tests for outer orchestration; no credentials/network/model calls."""
import importlib.util
import json
import os
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[1] / 'experiments/retrieval_method/chapter2_grading_supervisor.py'
spec = importlib.util.spec_from_file_location('grading_supervisor', SOURCE)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def closed(count, **changes):
    return dict(completed_scores=count, score_bindings_verified=True,
                all_scores_before_continuation_preserved=True, orphan_judge_requests=0, **changes)


class Fake:
    def __init__(self, probes=None, counts=None):
        self.calls = []
        self.probes = iter(probes or [dict(passed=True, permanent_rejection=False)])
        self.counts = iter(counts or [5363, 17136])
        self.number = 7
        self.audit_change = {}

    def wait_closed(self, attempt):
        self.calls.append(('wait_closed', attempt))

    def audit(self, attempt, prior):
        self.calls.append(('audit', attempt, prior))
        value = closed(next(self.counts))
        value.update(self.audit_change)
        return value

    def prepare_next(self):
        self.number += 1
        self.calls.append(('prepare', self.number))
        return self.number

    def probe(self, number):
        self.calls.append(('probe', number))
        return next(self.probes)

    def archive_probe(self):
        self.calls.append(('archive',))

    def cooldown(self):
        self.calls.append(('cooldown',))

    def score(self, number, prior, existing):
        self.calls.append(('score_only_unattempted', number, prior, existing))
        return f'scoring_execution_{number:03d}'


def test_wait_and_audit_precede_probe_and_score_and_bind_prior():
    f = Fake()
    assert m.supervise(f, 'scoring_execution_007', 'scoring_execution_006')['completed_scores'] == 17136
    assert f.calls == [
        ('wait_closed', 'scoring_execution_007'), ('audit', 'scoring_execution_007', 'scoring_execution_006'),
        ('prepare', 8), ('probe', 8), ('archive',),
        ('score_only_unattempted', 8, 'scoring_execution_007', 5363),
        ('wait_closed', 'scoring_execution_008'), ('audit', 'scoring_execution_008', 'scoring_execution_007')]


@pytest.mark.parametrize('change', [dict(score_bindings_verified=False),
    dict(all_scores_before_continuation_preserved=False), dict(orphan_judge_requests=1),
    dict(completed_scores=17137), dict(completed_scores=0)])
def test_no_model_admission_after_integrity_failure(change):
    f = Fake()
    f.audit_change = change
    with pytest.raises(ValueError):
        m.supervise(f, 'scoring_execution_007', 'scoring_execution_006')
    assert not any(x[0] in ('prepare', 'probe', 'score_only_unattempted') for x in f.calls)


def test_complete_matrix_never_probes_or_scores_again():
    f = Fake(counts=[17136])
    m.supervise(f, 'scoring_execution_007', 'scoring_execution_006')
    assert len(f.calls) == 2


def test_three_failed_independent_probes_never_admit_formal_score():
    f = Fake(probes=[dict(passed=False, permanent_rejection=False)] * 3)
    with pytest.raises(RuntimeError, match='Three independent probes'):
        m.supervise(f, 'scoring_execution_007', 'scoring_execution_006')
    assert [x for x in f.calls if x[0] == 'probe'] == [('probe', 8), ('probe', 9), ('probe', 10)]
    assert len([x for x in f.calls if x[0] == 'archive']) == 3
    assert not any(x[0] == 'score_only_unattempted' for x in f.calls)


def test_billing_rejection_archived_and_stops_without_another_probe():
    f = Fake(probes=[dict(passed=False, permanent_rejection=True)])
    with pytest.raises(RuntimeError, match='authorization/billing'):
        m.supervise(f, 'scoring_execution_007', 'scoring_execution_006')
    assert f.calls[-1] == ('archive',)
    assert len([x for x in f.calls if x[0] == 'probe']) == 1


def test_transient_probe_failure_uses_new_number_before_formal_continuation():
    f = Fake(probes=[dict(passed=False, permanent_rejection=False),
                     dict(passed=True, permanent_rejection=False)])
    m.supervise(f, 'scoring_execution_007', 'scoring_execution_006')
    assert ('score_only_unattempted', 9, 'scoring_execution_007', 5363) in f.calls
    assert not any(x[0] == 'score_only_unattempted' and x[1] == 8 for x in f.calls)


def test_no_progress_stops_before_third_formal_phase():
    f = Fake(counts=[5363, 5363])
    with pytest.raises(ValueError, match='no new terminal'):
        m.supervise(f, 'scoring_execution_007', 'scoring_execution_006')
    assert len([x for x in f.calls if x[0] == 'score_only_unattempted']) == 1


def test_missing_native_exit_after_real_process_terminal_cannot_restart(tmp_path):
    backend = object.__new__(m.Backend)
    backend.activity = tmp_path
    class Dead:
        def alive(self): return False
        def close(self): pass
    backend.process = Dead()
    with pytest.raises(RuntimeError, match='no native exit'):
        backend.wait_closed('scoring_execution_007')


def test_changed_driver_blocks_before_popen(tmp_path, monkeypatch):
    backend = object.__new__(m.Backend)
    backend.workspace = tmp_path
    backend.config = dict(driver_sha256={'.local/run.py': '0' * 64})
    (tmp_path / '.local').mkdir()
    (tmp_path / '.local/run.py').write_text('changed', encoding='utf-8')
    monkeypatch.setattr(m.subprocess, 'Popen', lambda *a, **k: pytest.fail('Must never start a child'))
    with pytest.raises(ValueError, match='driver changed'):
        backend.run('run.py', [])


def test_side_audit_failure_drains_child_before_reporting_failure(tmp_path):
    backend = object.__new__(m.Backend)
    backend.workspace = tmp_path
    backend.folder = tmp_path
    backend.latest = 5363
    backend.last_heartbeat = 0.0
    backend.process = None
    backend.activity = tmp_path / 'activity'
    (tmp_path / '.local').mkdir()
    child = tmp_path / '.local/child.py'
    child.write_text("from pathlib import Path\nprint(\"{'scored': 5364, 'status': 'judged'}\",flush=True)\nPath('child-drained').write_text('yes')\n", encoding='utf-8')
    backend.config = dict(driver_sha256={'.local/child.py': m.sha(child)}, python=m.sys.executable)
    backend.check_sources = lambda: None
    def fail(line):
        raise ValueError('side audit failed')
    with pytest.raises(ValueError, match='side audit failed'):
        backend.run('child.py', [], fail)
    assert (tmp_path / 'child-drained').read_text() == 'yes'


@pytest.mark.skipif(os.name != 'nt', reason='Windows process identity contract')
def test_actual_process_handle_binds_creation_time_and_rejects_reused_identity():
    kernel = m.ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GetCurrentProcess.restype = m.wintypes.HANDLE
    kernel.GetProcessTimes.argtypes = [m.wintypes.HANDLE] + [m.ctypes.POINTER(m.wintypes.FILETIME)] * 4
    times = [m.wintypes.FILETIME() for _ in range(4)]
    assert kernel.GetProcessTimes(kernel.GetCurrentProcess(), *(m.ctypes.byref(x) for x in times))
    creation = (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
    process = m.WindowsProcess(os.getpid(), creation)
    assert process.alive()
    process.close()
    with pytest.raises(ValueError, match='creation identity changed'):
        m.WindowsProcess(os.getpid(), creation + 1)


@pytest.mark.skipif(os.name != 'nt', reason='Windows exclusive supervisor lease')
def test_second_supervisor_lease_is_rejected_and_lease_can_later_recover(tmp_path):
    path = tmp_path / 'lease'
    with m.exclusive_supervisor_lease(path):
        with pytest.raises(OSError):
            with m.exclusive_supervisor_lease(path):
                pytest.fail('A second supervisor must not acquire the active lease')
    with m.exclusive_supervisor_lease(path):
        pass
