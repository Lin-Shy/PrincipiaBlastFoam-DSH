from test_evidence_bundle import SKILL
import cpp_inputs as cpp


H='''template<class Base> class Demo : public Base {
static word typeName() { return "demo<" + Base::typeName() + '>'; }
};'''


def extract(initializers,body=''):
    source='Foam::Demo<Base>::Demo(const dictionary& config) : Base(config), '+initializers+' {'+body+'}'
    result=cpp.analyze(source,H)
    assert not result['diagnostics']
    return result['models'][0]


def test_direct_and_default_dependencies_preserve_expressions_and_base_scope():
    m=extract('A_(config.subDict("coeffs").lookup<scalar>("A")), '
              'B_(config.subDict("coeffs").lookupOrDefault<scalar>("B", 2*A_)), '
              'C_(config.subDict("coeffs").lookupOrDefault("C", externalValue))')
    assert m['complete_local_reads']
    a,b,c=m['inputs']
    assert (a['dictionary'],a['key'],a['requirement'])==('coeffs','A','required')
    assert b['default_expression']=='2*A_' and b['default_dependencies']==['coeffs/A']
    assert b['requirement']=='optional' and b['default_kind']=='expression'
    assert c['unresolved_default_symbols']==['externalValue']
    assert m['dictionary_forwarding'][0]['callee']=='Base'
    assert m['dictionary_forwarding'][0]['specialization']=='unresolved'


def test_dictionary_alias_and_nested_subdictionary_keep_evidence():
    m=extract('A_(0)', 'const dictionary& local = config.subDict("outer"); '
              'A_ = readScalar(local.subDict("inner").lookup("A"));')
    assert m['complete_local_reads']
    a=m['inputs'][0]
    assert a['dictionary']=='outer/inner'
    assert 'const dictionary& local' in a['evidence'][1]['text']


def test_conditions_are_not_unconditional_requirements():
    m=extract('A_(0)', 'if (config.found("switch")) { A_=config.subDict("coeffs").lookup<scalar>("A"); } '
              'else { A_=config.subDict("other").lookupOrDefault<scalar>("A", 1); }')
    assert len(m['inputs'])==2
    assert all(x['requirement']=='conditional' for x in m['inputs'])
    assert [x['conditions'][0]['branch'] for x in m['inputs']]==['then','else']
    assert not m['complete_local_reads']  # found() not evaluated into current state.


def test_conditional_initializer_cannot_be_flattened():
    m=extract('A_(enabled ? config.subDict("coeffs").lookup<scalar>("A") : 0)')
    assert m['inputs'][0]['requirement']=='conditional'


def test_macros_dynamic_keys_and_shadowed_aliases_fail_closed():
    assert not extract('A_(READ(config, "A"))')['complete_local_reads']
    m=extract('A_(config.subDict("coeffs").lookup<scalar>(keyName))')
    assert not m['inputs'] and not m['complete_local_reads']
    m=extract('A_(0)', '{ const dictionary& local = config.subDict("x"); A_=local.lookup<scalar>("A"); }')
    assert not m['inputs'] and not m['complete_local_reads']


def test_comment_reads_and_unrelated_helpers_do_not_create_inputs():
    source='''Foam::Other<Base>::readOne(const word& key, const dictionary& config)
{ return config.subDict("bad").lookup<scalar>(key); }
Foam::Demo<Base>::Demo(const dictionary& config) : Base(config),
A_(readOne("A", config)) { /* config.lookup<scalar>("invented"); */ }
'''
    m=cpp.analyze(source,H)['models'][0]
    assert not m['inputs'] and not m['complete_local_reads']


def test_helper_and_direct_reads_are_combined():
    source='''Foam::scalar Foam::Demo<Base>::readOne(const word& key, const dictionary& config)
{ return config.subDict("coeffs").lookup<scalar>(key); }
Foam::Demo<Base>::Demo(const dictionary& config) : Base(config),
A_(readOne("A", config)), B_(config.subDict("coeffs").lookup<scalar>("B")) {}
'''
    m=cpp.analyze(source,H)['models'][0]
    assert m['complete_local_reads'] and [f['key'] for f in m['inputs']]==['A','B']
    assert len(m['inputs'][0]['evidence'])==2


def test_constructor_overloads_are_explicit_and_not_merged():
    source='''Foam::Demo<Base>::Demo(const dictionary& config) : Base(config), A_(config.lookup<scalar>("A")) {}
Foam::Demo<Base>::Demo(const Base& b, const dictionary& config) : Base(b), B_(config.lookup<scalar>("B")) {}'''
    models=cpp.analyze(source,H)['models']
    assert [m['dictionary_only_constructor'] for m in models]==[True,False]
    assert [[f['key'] for f in m['inputs']] for m in models]==[['A'],['B']]


def test_unresolved_member_dictionary_delegate_is_not_an_inherited_schema():
    m=extract('A_(config.subDict("coeffs").lookup<scalar>("A")), table_(config)')
    assert not m['complete_local_reads']
    assert m['dictionary_forwarding'][-1]['callee_kind']=='unresolved_delegate'
