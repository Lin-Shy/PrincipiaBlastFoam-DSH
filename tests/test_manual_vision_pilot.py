"""Visual evidence must remain traceable and budget truncation must not corrupt equations."""
import importlib.util
import json
from pathlib import Path
import sys

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]/'.dsh/skills/blastfoam-knowledge/scripts'
sys.path.insert(0, str(SCRIPTS))
v = pytest.importorskip('manual_vision', reason='用户已采用外部高保真 Markdown 并移除视觉试抽流程')
import export_manual_pilot as e


@pytest.mark.parametrize('refs', [[], ['context'], ['foreign'], ['missing']])
def test_rejects_wrong_visual_provenance(refs):
    section = {'images': ['target', 'context']}
    plan = {'images': {'target': {'role': 'target'}, 'context': {'role': 'context'}, 'foreign': {'role': 'target'}}}
    with pytest.raises(ValueError, match='provenance'):
        v.validate_payload({'blocks': [{'kind': 'formula', 'content': 'ρ', 'source_images': refs}]}, section, plan)


def test_formula_and_section_note_fit_or_are_omitted_together():
    formula = {'id': 'S01-b001', 'kind': 'formula', 'content': 'special', 'number': '(1)', 'source_images': ['img']}
    note = {'id': 'S01-b002', 'kind': 'text', 'content': 'NOTE: '+('condition '*70), 'source_images': ['img']}
    data = {'sections': [{'id': 'S01', 'hierarchy': [{'title': 'special'}], 'blocks': [formula, note]}],
            'images': {'img': {'path': 'images/eq.png', 'pdf_page': 1}},
            'edges': [{'source': formula['id'], 'target': note['id'], 'relation': 'SECTION_NOTE'}]}
    small = e.packet(data, 'special', budget=400)
    assert formula['id'] not in small['selected']
    assert len(small['markdown']) <= 400
    large = e.packet(data, 'special', budget=2000)
    assert set(large['selected']) == {formula['id'], note['id']}
    assert '![公式' in large['markdown'] and 'NOTE:' in large['markdown']


def test_viewer_embedding_cannot_close_script():
    value = {'content': '</script><script>alert(1)</script>\u2028ρ'}
    encoded = e.safe_json(value)
    assert '</script>' not in encoded
    assert json.loads(encoded) == value


def test_short_symbol_definition_remains_a_graph_node(tmp_path, monkeypatch):
    section = {'id': 'S01', 'title': 'Example', 'hierarchy': [{'id': 'toc-001', 'title': 'Example'}], 'images': ['img']}
    plan = {'snapshot': 'snapshot', 'source_sha256': 'pdf', 'sections': [section],
            'images': {'img': {'role': 'target', 'path': 'img.png', 'sha256': 'image'}}}
    payload = {'boundary_check': 'complete', 'blocks': [
        {'kind': 'text', 'content': 'where V = ρ₀/ρ.', 'source_images': ['img']},
        {'kind': 'text', 'content': 'and', 'source_images': ['img']}]}
    v.write(tmp_path/'responses/S01.json', {'status': 'ok', 'snapshot': 'snapshot', 'raw_response': {
        'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(payload)}}]}})
    monkeypatch.setattr(v, 'checked_plan', lambda _: plan)
    monkeypatch.setattr(v, 'sha', lambda _: 'image')
    graph = e.collect(tmp_path)
    ids = {n['id'] for n in graph['nodes']}
    assert 'S01-b001' in ids
    assert 'S01-b002' not in ids
    assert len(graph['sections'][0]['blocks']) == 2


def test_direct_markdown_preserves_math_and_splits_shared_provenance():
    section = {'title': 'Model', 'images': ['target'], 'segments': [{'images': ['target']}]}
    plan = {'images': {'target': {'role': 'target', 'path': 'images/target.png'}}}
    source = r'''## Model

<!-- source: target -->
Density is $\rho_i$.

<!-- source: target -->
$$
\mathbf{U}=\begin{pmatrix}\rho\\\rho u\end{pmatrix}\tag{1}
$$
'''
    p = v.parse_markdown(source, section, plan)
    assert [b['kind'] for b in p['blocks']] == ['heading', 'text', 'formula']
    formula = p['blocks'][-1]
    assert formula['content'] == r'\mathbf{U}=\begin{pmatrix}\rho\\\rho u\end{pmatrix}\tag{1}'
    assert p['normalizations'] == ['heading_source_from_verified_section_boundary']
    exported = e.block_md({**formula, 'id': 'S01-b003'}, plan['images'])
    assert '$$' in exported and r'\begin{pmatrix}' in exported
    assert '![' not in exported
    shared = v.parse_markdown('<!-- source: target -->\n# Model\n\nOriginal paragraph.', section, plan)
    assert [b['kind'] for b in shared['blocks']] == ['heading', 'text']


def test_only_traceable_figures_may_embed_images():
    section = {'title': 'Model', 'images': ['target']}
    plan = {'images': {'target': {'role': 'target', 'path': 'images/target.png'}}}
    figure = v.parse_markdown('<!-- source: target -->\n![Diagram](images/target.png)', section, plan)['blocks'][0]
    assert figure['kind'] == 'figure'
    assert '../images/target.png' in e.block_md({**figure, 'id': 'figure'}, plan['images'])
    with pytest.raises(ValueError, match='traceable'):
        v.parse_markdown('<!-- source: target -->\n![Diagram](https://example.com/other.png)', section, plan)
    with pytest.raises(ValueError, match='traceable'):
        v.parse_markdown('<!-- source: target -->\n$$\n![Equation](images/target.png)\n$$', section, plan)
