"""Validate evolving design documents through exact Manifest-bound old bytes.

Every original binding check still runs. Only the two shared research documents
resolve to reviewed frozen copies during startup validation; scoring and all
other paths continue to use the real workspace.
"""
from functools import wraps
from pathlib import Path
import single_pass_dev40 as s

BASE = s.RUN/'test160_runs'
REVIEW = BASE/'research_binding_review_20261102/review.json'
CONTROL = BASE/'gpt_concurrency_control_20261102.json'


class WorkspaceView:
    def __init__(self, original, overrides):
        self.original = original
        self.overrides = overrides

    def __truediv__(self, relative):
        return self.overrides.get(Path(relative).as_posix(), self.original/relative)

    def __getattr__(self, name):
        return getattr(self.original, name)


def install(evaluation):
    if getattr(evaluation.authorize, '_frozen_research_view', False):
        return
    original_authorize = evaluation.authorize

    @wraps(original_authorize)
    def authorize(path, mode='agentic'):
        control = s.load(CONTROL)
        assert control['exact_hash_research_copies_authorized'] is True
        manifest = s.load(evaluation.runner.MANIFEST)
        review = s.load(REVIEW)
        original = s.WORKSPACE
        overrides = {}
        expected_paths = {'graduation-thesis-materials/graduation-research/README.md',
                          'graduation-thesis-materials/graduation-research/OVERVIEW.md'}
        assert {r['original_path'] for r in review['files']} == expected_paths
        for row in review['files']:
            snapshot = original/row['proposed_frozen_copy']
            assert snapshot.resolve().is_relative_to(REVIEW.parent.resolve())
            assert s.sha(snapshot) == row['frozen_sha256'] == manifest['bindings'][row['original_path']]
            overrides[row['original_path']] = snapshot
        s.WORKSPACE = WorkspaceView(original, overrides)
        try:
            # Runs the unchanged scope, ALL bindings, question split and
            # deployment checks. No hash or authorization check is omitted.
            return original_authorize(path, mode)
        finally:
            s.WORKSPACE = original

    authorize._frozen_research_view = True
    evaluation.authorize = authorize
