from pathlib import Path
import importlib.util

from experiments.retrieval_method.navigation_structure_parser import dictionary


PARSER = Path(__file__).resolve().parents[1] / ".dsh/skills/blastfoam-knowledge/scripts/knowledge.py"
spec = importlib.util.spec_from_file_location("structure_test_knowledge", PARSER)
knowledge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(knowledge)


def parse(text):
    return dictionary(text, knowledge.lex)


def test_parent_headers_full_paths_and_physical_values():
    text = 'phaseA\n{\n thermoType { transport chosen; }\n transport { c 12; }\n}\nphaseB { transport { c 19; } }\n'
    result = parse(text)
    rows = {r["dictionary_path"]: r for r in result["records"]}
    assert rows["phaseA/transport/c"]["value_text"] == "12"
    assert rows["phaseB/transport/c"]["value_text"] == "19"
    assert rows["phaseA"]["open_line"] == 2
    assert rows["phaseA"]["line_end"] == 5
    assert rows["phaseA/transport/c"]["parent"] == rows["phaseA/transport"]["ordinal"]
    assert all(r["status"] == "literal_physical_structure" for r in rows.values())
    assert text[rows["phaseA"]["start_offset"]:rows["phaseA"]["end_offset"]] == rows["phaseA"]["raw"]


def test_missing_semicolon_does_not_become_a_verified_combined_value():
    rows = parse('schemes {\n alpha first\n beta second;\n last unfinished\n}')['records']
    swallowed = next(r for r in rows if r['key'] == 'alpha')
    assert 'multiline_plain_value_needs_syntax_check' in swallowed['flags']
    assert swallowed['status'] == 'unresolved_static_source'
    last = next(r for r in rows if r['key'] == 'last')
    assert last['kind'] == 'unresolved_statement'
    assert 'unterminated_statement' in last['flags']


def test_duplicate_blocks_and_descendants_do_not_silently_choose_last():
    rows = parse('a { x 1; } a { x 2; } value 3; value 4;')['records']
    bypath = {r['dictionary_path']: r for r in rows}
    assert bypath['a/x']['value_text'] == '1'
    assert bypath['a@2/x']['value_text'] == '2'
    assert bypath['a/x']['status'] == bypath['a@2/x']['status'] == 'unresolved_static_source'
    assert 'duplicate_sibling_name_not_resolved' in bypath['value']['flags']
    assert 'duplicate_sibling_name_not_resolved' in bypath['value@2']['flags']


def test_conditional_include_and_code_are_never_executed():
    text = '#if $flag\na { x 1; }\n#else\na { x 2; }\n#endif\n#include "frag"\ncalc #codeStream { code #{ ignored ; } #}; };\n'
    result = parse(text)
    xs = [r for r in result['records'] if r['key'] == 'x']
    assert len(xs) == 2 and all(r['conditional_context'] for r in xs)
    assert xs[0]['conditional_context'][0]['branch'] == 'if'
    assert xs[1]['conditional_context'][0]['branch'] == 'else'
    include = next(r for r in result['records'] if r['key'] == '#include')
    assert include['argument_text'] == '"frag"'
    assert include['status'] == 'unresolved_static_source'
    assert not any(r['key'] == 'ignored' for r in result['records'])


def test_operator_keys_quotes_lists_and_escaped_component_boundaries():
    rows = parse('divSchemes { div(phi,U) Gauss linear; "a/b" 3; }\npoints\n((1 2 3) (4 5 6));\n')['records']
    bypath = {r['dictionary_path']: r for r in rows}
    assert bypath['divSchemes/div(phi,U)']['value_text'] == 'Gauss linear'
    assert bypath['divSchemes/a~1b']['physical_components'][-1]['key'] == 'a/b'
    assert bypath['points']['status'] == 'literal_physical_structure'
    assert bypath['points']['value_text'] == '((1 2 3) (4 5 6))'


def test_unclosed_parents_mark_descendants_unresolved_and_lists_are_opaque():
    result = parse('a { b { x 1; }\n')
    assert all(r['status'] == 'unresolved_static_source' for r in result['records'])
    result = parse('regions (shape { centre (1 2 3); });\n')
    assert len(result['records']) == 1
    assert 'embedded_dictionary_value_not_expanded' in result['records'][0]['flags']
