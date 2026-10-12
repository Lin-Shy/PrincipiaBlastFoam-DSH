"""本地include片段的结构提取；不依赖问答题及其答案。"""
import importlib.util
from pathlib import Path
import sys

import pytest


SKILL = Path(__file__).resolve().parents[1] / '.dsh/skills/blastfoam-knowledge'
# The standalone entrypoint adds this directory implicitly. Mirror it when
# loading knowledge.py by filename, including its deferred manual_graph import.
sys.path.insert(0, str(SKILL/'scripts'))
spec = importlib.util.spec_from_file_location('include_knowledge', SKILL/'scripts/knowledge.py')
k = importlib.util.module_from_spec(spec)
spec.loader.exec_module(k)


@pytest.fixture
def corpus(tmp_path):
    root = tmp_path/'corpus'
    sources = {
        'tutorials/demo/Allrun': 'runApplication blockMesh\n',
        'tutorials/demo/system/controlDict': 'FoamFile {format ascii;} application blastFoam;\n',
        'tutorials/demo/constant/phaseProperties': 'FoamFile {format ascii;}\n#include "species.data"\n',
        'tutorials/demo/constant/species.data': 'oxygen { transport { As 1.2e-6; Ts 150; } }\n#include "extra.inc"\n',
        'tutorials/demo/constant/extra.inc': 'nitrogen { transport { As 2.3e-6; Ts 110; } }\n#include "species.data"\n',
        'tutorials/demo/constant/unreferenced.data': 'secretUnused 99;\n',
        'manual/markdown/01_models.md': '# Models\n\n## transport\n\nTransport coefficients.\n',
    }
    for name, text in sources.items():
        path = root/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return root


def test_headerless_fragments_gain_physical_scopes_without_execution(corpus, tmp_path):
    off = tmp_path/'off'; on = tmp_path/'on'
    k.build(SKILL, corpus, off, parse_included_dictionaries=False)
    k.build(SKILL, corpus, on, parse_included_dictionaries=True)
    graphs = [k.read_json(k.release_path(folder)/'graph.json') for folder in (off,on)]
    prefix = 'config:tutorials/demo/constant/species.data:'
    assert not any(n['id'].startswith(prefix) for n in graphs[0]['nodes'])
    entries = {n['id']: n for n in graphs[1]['nodes'] if n['kind']=='configuration'}
    assert entries[prefix+'oxygen/transport/As']['value']=='1.2e-6'
    assert entries[prefix+'oxygen/transport/Ts']['evidence']['path'].endswith('species.data')
    assert entries[prefix+'oxygen/transport/Ts']['evidence_status']=='tutorial_observed'
    assert any('extra.inc:nitrogen/transport/Ts' in uid for uid in entries)
    assert not any('unreferenced.data' in uid for uid in entries)
    assert k.read_json(k.release_path(on)/'manifest.json')['literal_include_targets']==2
    assert (corpus/'tutorials/demo/constant/species.data').read_text().startswith('oxygen')


def test_comments_macros_and_outside_paths_never_become_dictionary_sources(corpus):
    source = corpus/'tutorials/demo/constant/phaseProperties'
    source.write_text('''FoamFile {format ascii;}
// #include "unreferenced.data"
/* #include "unreferenced.data" */
#codeStream #{ #include "unreferenced.data" #}
#include "$UNRESOLVED/secret"
#include "../../../../outside"
#includeIfPresent "missing.inc"
#include "species.data"
''')
    inventory = k.scan(corpus)
    targets, issues = k.literal_dictionary_includes(corpus,inventory,[p for p in inventory if p.startswith('tutorials/')])
    assert set(targets)=={'tutorials/demo/constant/species.data','tutorials/demo/constant/extra.inc'}
    reasons = {i['reason'] for i in issues}
    assert {'include_target_unresolved','include_target_outside_corpus','include_target_unavailable'} <= reasons
    assert any(i.get('optional') is True for i in issues)


def test_build_identity_changes_when_include_mode_changes(corpus, tmp_path):
    index=tmp_path/'index'
    first=k.build(SKILL,corpus,index,parse_included_dictionaries=False)
    second=k.build(SKILL,corpus,index,parse_included_dictionaries=True)
    assert first['snapshot']!=second['snapshot']
    assert k.build(SKILL,corpus,index,parse_included_dictionaries=True)['status']=='unchanged'
    changed=corpus/'tutorials/demo/constant/extra.inc'
    changed.write_text('nitrogen { transport { Ts 125; } }\n')
    third=k.build(SKILL,corpus,index,parse_included_dictionaries=True)
    assert third['snapshot']!=second['snapshot']


def test_include_reachability_changes_invalidate_unchanged_fragment_cache(corpus, tmp_path):
    index = tmp_path/'index'
    k.build(SKILL, corpus, index, parse_included_dictionaries=True)
    root = corpus/'tutorials/demo/constant/phaseProperties'
    root.write_text('FoamFile {format ascii;}\n')
    k.build(SKILL, corpus, index, parse_included_dictionaries=True)
    changed = k.read_json(k.release_path(index)/'graph.json')
    assert not any(n['kind']=='configuration' and 'species.data' in n['id'] for n in changed['nodes'])
    fresh = tmp_path/'fresh'
    k.build(SKILL, corpus, fresh, parse_included_dictionaries=True)
    assert changed == k.read_json(k.release_path(fresh)/'graph.json')
    root.write_text('FoamFile {format ascii;}\n#include "species.data"\n')
    k.build(SKILL, corpus, index, parse_included_dictionaries=True)
    restored = k.read_json(k.release_path(index)/'graph.json')
    assert any(n['kind']=='configuration' and 'species.data' in n['id'] for n in restored['nodes'])


def test_literal_include_can_promote_dictionary_with_data_extension(corpus, tmp_path):
    (corpus/'tutorials/demo/constant/params.dat').write_text('coefficient 17;\n')
    (corpus/'tutorials/demo/constant/phaseProperties').write_text('FoamFile {format ascii;}\n#include "params.dat"\n')
    index = tmp_path/'index'
    k.build(SKILL, corpus, index, parse_included_dictionaries=True)
    graph = k.read_json(k.release_path(index)/'graph.json')
    assert any(n['id']=='config:tutorials/demo/constant/params.dat:coefficient' for n in graph['nodes'])
