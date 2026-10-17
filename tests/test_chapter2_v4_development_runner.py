from pathlib import Path
import sys
from threading import RLock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'experiments/retrieval_method'))
from chapter2_qa_backends import NativeBackend
from chapter2_v4_development_runner import clone_backend
from chapter2_knowledge_backends_v4 import HybridNativeView
from chapter2_backend_process import BackendProcess, RemoteBackend
import json
import os
import pytest


class Engine:
    def query(self, query, plan, limit):
        return dict(items=[dict(path='manual/a', ranges=[dict(start=1, end=2)])]), dict(query=query)


def test_native_session_events_are_isolated_while_engine_and_lock_are_shared():
    template = NativeBackend(Engine()); lock = RLock()
    left = clone_backend(template, lock); right = clone_backend(template, lock)
    assert left.lock is right.lock is lock and left.engine is right.engine
    left.search('pressure', 10)
    assert len(left.events) == 1 and not right.events and not template.events


def test_hybrid_session_events_are_isolated_and_keep_exact_existing_fusion():
    template = HybridNativeView(NativeBackend(Engine()), NativeBackend(Engine())); lock = RLock()
    left = clone_backend(template, lock); right = clone_backend(template, lock)
    assert left.search('pressure', 10) == [dict(path='manual/a', start=1, end=2)]
    assert len(left.events) == 1 and not right.events and not template.events
    assert left.events[0]['fusion'] == 'RRF_k60_pool64'


def test_none_arm_never_instantiates_backend_or_event_log():
    assert clone_backend(None, RLock()) is None


def test_real_graph_worker_has_no_baseline_dependencies_and_isolates_sessions(tmp_path):
    from test_chapter2_graph_source_context import fixture
    _, engine = fixture(tmp_path, {'manual/models.md': '# Models\n## Pressure\npressure target\n'})
    resources = tmp_path / 'resources.json'
    resources.write_text(json.dumps(dict(corpus=str(engine.root), source_map=str(tmp_path / 'authority.json'),
        graph_full=str(tmp_path / 'graph.json'))), encoding='utf-8')
    questions = tmp_path / 'questions.json'
    questions.write_text('[]', encoding='utf-8')
    server = BackendProcess('graph', resources, questions)
    try:
        assert server.receipt['pid'] != os.getpid()
        assert server.receipt['graph_process'] and not server.receipt['baseline_dependencies_loaded']
        assert server.receipt['input_guard']['subprocess_disabled']
        left = RemoteBackend(server); right = clone_backend(left, RLock())
        rows = left.search('pressure', 10)
        assert rows and all(r['path'] == 'manual/models.md' for r in rows)
        assert len(left.events) == 1 and not right.events
        assert right.search('pressure', 10) == rows
        assert len(left.events) == len(right.events) == 1
    finally:server.close()
    assert server.process.returncode == 0


@pytest.mark.parametrize('method,expected', [('graph','adjacent'),('adjacent_only','adjacent'),
    ('parent_blanket','blanket'),('no_context','none'),('no_cross','adjacent')])
def test_selected_context_applies_to_structural_ablations_but_keeps_explicit_context_controls(tmp_path,method,expected):
    from test_chapter2_graph_source_context import fixture
    _, engine = fixture(tmp_path, {'manual/models.md': '# Models\n## Pressure\npressure target\n'})
    resources=tmp_path/'resources.json'
    resources.write_text(json.dumps(dict(corpus=str(engine.root),source_map=str(tmp_path/'authority.json'),
        graph_full=str(tmp_path/'graph.json'),graph_no_cross=str(tmp_path/'graph.json'))),encoding='utf-8')
    questions=tmp_path/'questions.json';questions.write_text('[]',encoding='utf-8')
    server=BackendProcess(method,resources,questions,context_policy='adjacent')
    try:
        assert server.receipt['context_policy']==expected
        assert not server.receipt['baseline_dependencies_loaded']
    finally:server.close()
