import json
from pathlib import Path
import sys
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'experiments/retrieval_method'))
from chapter2_lossless_json import encode, save


def test_roundtrip_keeps_unpaired_surrogates_and_normal_unicode(tmp_path):
    value = {'text': '中文\udb06Q', 'literal': r'\udb06', 'emoji': '😀'}
    path = tmp_path / 'result.json'
    save(path, value)
    assert json.loads(path.read_text(encoding='utf-8')) == value
    assert b'\\udb06' in path.read_bytes()
    assert '中文'.encode('utf-8') in path.read_bytes()
    assert not list(tmp_path.glob('*.tmp'))


def test_valid_values_keep_original_serialization_bytes():
    value = {'text': '正常中文', 'rows': [1, None, True]}
    assert encode(value) == json.dumps(value, ensure_ascii=False, indent=2).encode('utf-8')


def test_failed_serialization_leaves_prior_artifact_unchanged(tmp_path):
    path = tmp_path / 'result.json'
    path.write_bytes(b'prior immutable artifact')
    with pytest.raises(TypeError): save(path, {'bad': object()})
    assert path.read_bytes() == b'prior immutable artifact'
