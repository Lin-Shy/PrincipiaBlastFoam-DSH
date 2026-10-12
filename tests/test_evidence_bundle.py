"""Budget, provenance and configuration-context checks on an unrelated fixture."""
import json
from pathlib import Path
import shutil
import sys

import pytest

SKILL = Path(__file__).resolve().parents[1] / '.dsh/skills/blastfoam-knowledge'
sys.path.insert(0, str(SKILL / 'scripts'))
import evidence_bundle as b


@pytest.fixture
def engine(tmp_path):
    corpus = tmp_path / 'corpus'
    (corpus / 'manual/markdown').mkdir(parents=True)
    (corpus / 'tutorials/caseA/system').mkdir(parents=True)
    (tmp_path / 'references').mkdir()
    shutil.copy(SKILL / 'references/terms.json', tmp_path / 'references/terms.json')
    (corpus / 'manual/markdown/01_sampling.md').write_text('# Models\n\n## 1.1 sampling\n\nThe sampled quantity is configured in fields.\n\n## 1.2 otherModel\n\nUnrelated definition in the same chapter.\n')
    (corpus / 'tutorials/caseA/README.md').write_text('Acoustic sampling verification example.\n')
    (corpus / 'tutorials/caseA/Allrun').write_text('runApplication blockMesh\n')
    (corpus / 'tutorials/caseA/system/blockMeshDict').write_text('FoamFile {version 2;}\nblocks (hex (0 1 2 3 4 5 6 7) (17 2 1));\n')
    (corpus / 'tutorials/caseA/system/controlDict').write_text('''FoamFile {version 2;}
application solver;
writeControl adjustableRunTime;
writeInterval 0.01;
functions
{
    sensor
    {
        type sampling;
        writeControl timeStep;
        writeInterval 1;
        probeLocations ((1 0 0));
        fields (p);
    }
}
''')
    b.k.build(SKILL, corpus, tmp_path / 'index')
    return b.EvidenceSearch(b.build(tmp_path), tmp_path)


def test_function_scope_retains_fields_and_separate_global_output(engine):
    packet, audit = engine.search('sampling pressure output', budget=4000, case='caseA')
    functions = [e for e in packet['evidence'] if e['scope'] == 'functions/sensor']
    assert functions and 'fields (p);' in functions[0]['text']
    assert any(e['scope'] == 'control' and '0.01' in e['text'] for e in packet['evidence'])
    assert any(e['relation'] == 'SEPARATE_OUTPUT_CONTROLS' for e in engine.graph['edges'])
    assert audit['retrieval_api_tokens'] == 0


@pytest.mark.parametrize('strategy', ['text', 'files', 'graph'])
@pytest.mark.parametrize('budget', [1000, 1800, 6000])
def test_all_strategies_preserve_exact_nonoverlapping_sources(engine, strategy, budget):
    packet, _ = engine.search('sampling mesh output', strategy, budget)
    assert len(b.wire(packet)) <= budget
    seen = set()
    for ev in packet['evidence']:
        path = packet['sources'][ev['source']]['path']
        ls = (engine.skill / 'corpus' / path).read_text().splitlines(keepends=True)
        assert ev['text'] == ''.join(ls[ev['start'] - 1:ev['end']])
        positions = {(path, i) for i in range(ev['start'], ev['end'] + 1)}
        assert not seen & positions
        seen |= positions


def test_source_changes_and_index_tampering_are_rejected(engine):
    p = engine.skill / 'corpus/tutorials/caseA/system/controlDict'
    p.write_text(p.read_text().replace('0.01', '0.02'))
    with pytest.raises(ValueError, match='corpus changed'):
        engine.search('sampling')
    engine.graph['cases'].append('invented')
    with pytest.raises(ValueError, match='digest mismatch'):
        engine.validate()


def test_graph_edges_do_not_claim_runtime_dependencies(engine):
    edges = [e for e in engine.graph['edges'] if e['relation'] == 'UTILITY_INPUT_CANDIDATE']
    assert edges and all(e['status'] == 'conventional_name_runtime_unverified' for e in edges)
    assert all(e['evidence'][0]['path'].endswith('/Allrun') for e in edges)
    p = engine.skill / 'corpus/tutorials/caseA/Allrun'
    p.write_text('runApplication blockMesh -dict alternativeDict\n')
    b.k.build(SKILL, engine.skill / 'corpus', engine.skill / 'index')
    derived = b.build(engine.skill)
    assert not any(e['relation'] == 'UTILITY_INPUT_CANDIDATE' for e in derived['edges'])


def test_no_match_bad_case_and_reproducible_build(engine):
    assert engine.search('zzznothing999')[0]['evidence'] == []
    with pytest.raises(ValueError, match='case_unavailable'):
        engine.search('sampling', case='missing')
    assert b.build(engine.skill) == engine.graph
    for args in [('',), ('sampling', 'unknown'), ('sampling', 'graph', True)]:
        with pytest.raises(ValueError):
            engine.search(*args)


def test_definition_expansion_stays_within_section_in_shared_markdown(engine):
    links = [e for e in engine.graph['edges'] if e['relation'] == 'REFERS_TO_DEFINITION']
    assert links
    for edge in links:
        target = engine.units[edge['target']]
        assert 'The sampled quantity' in engine.raw(target)
        assert 'Unrelated definition' not in engine.raw(target)


def test_pinned_solver_code_is_searchable_and_not_parsed_as_configuration(engine):
    code=engine.skill/'corpus/manual/source_code/example.C';code.parent.mkdir(parents=True)
    code.write_text('void viscousPrototypeMethod() { if (mu > 0) { solveMomentum(); } }\n')
    result=b.k.build(SKILL,engine.skill/'corpus',engine.skill/'index')
    release=b.k.release_path(engine.skill/'index')
    docs=b.k.read_json(release/'documents.json')
    assert any(d['source_scope']=='solver_code' and 'viscousPrototypeMethod' in d['text'] for d in docs)
    graph=b.k.read_json(release/'graph.json')
    assert not any(n['kind']=='configuration' and n['evidence']['path'].endswith('example.C') for n in graph['nodes'])
    search=b.EvidenceSearch(b.build(engine.skill),engine.skill)
    assert any(u['path']=='manual/source_code/example.C' for u in search.units.values())
