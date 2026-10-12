"""Portable visualization exports must preserve evidence without executable input."""
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '.dsh/skills/blastfoam-knowledge/scripts'))
import export_visualization as v


def test_json_embedding_cannot_close_script():
    data = {'text': '</script><script>alert(1)</script>\u2028\u2029 & 中文'}
    encoded = v.safe_json(data)
    assert '<' not in encoded and '\u2028' not in encoded and '\u2029' not in encoded
    assert json.loads(encoded) == data


def test_svg_source_labels_are_xml_escaped():
    layer = {'nodes':[{'id':'a','group':'case<&>'},{'id':'b','group':'manual'}],
             'edges':[{'source':'a','target':'b'}]}
    root = ET.fromstring(v.overview_svg(layer))
    assert 'case<&>' in ''.join(root.itertext())


def test_export_preserves_complete_data_and_refuses_overwrite(tmp_path, monkeypatch):
    layer = {'id':'configuration','name':'配置证据图','snapshot':'test',
             'nodes':[{'id':str(i),'group':'case'} for i in range(1001)],'edges':[]}
    data = {'layers':[layer], 'sources':{'x':{'text':'</script>原文\n','sha256':'x'}},'grouping':'case'}
    monkeypatch.setattr(v, 'collect', lambda *args: data)
    output = tmp_path/'export';result = v.export(output)
    assert result['layers'][0]['nodes'] == 1001
    assert json.loads((output/'graph.json').read_text()) == data
    page=(output/'graph.html').read_text()
    embedded=page.split('<script id="graph-data" type="application/json">')[1].split('</script>')[0]
    assert json.loads(embedded) == data
    with pytest.raises(ValueError, match='empty output'):
        v.export(output)
