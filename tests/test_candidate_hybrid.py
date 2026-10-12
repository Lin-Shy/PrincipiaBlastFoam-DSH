from pathlib import Path

import pytest

from experiments.retrieval_method import candidate_hybrid as hybrid


def test_embedding_snapshot_resolves_to_exact_frozen_revision(tmp_path, monkeypatch):
    revision='abc123'
    snapshot=tmp_path/'models--org--model'/'snapshots'/revision
    snapshot.mkdir(parents=True)
    monkeypatch.setenv('HF_HUB_CACHE',str(tmp_path))
    assert hybrid.local_snapshot({'model':'org/model','revision':revision}) == snapshot


def test_embedding_snapshot_refuses_remote_fallback(tmp_path):
    with pytest.raises(FileNotFoundError,match='frozen embedding snapshot is unavailable'):
        hybrid.local_snapshot({'model':'org/model','revision':'missing','cache_folder':str(tmp_path)})
