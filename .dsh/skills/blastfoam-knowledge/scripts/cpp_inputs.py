"""Bounded, source-only analysis of OpenFOAM dictionary constructors.

This deliberately does not compile C++, expand macros, evaluate expressions or
specialize template bases. Every read is tied to a constructor and a dictionary
receiver. Unsupported dictionary uses and control flow remain explicit gaps.
"""
from dataclasses import dataclass
import re


@dataclass(frozen=True)
class Token:
    value: str
    start: int
    end: int


TOKEN = re.compile(r'//[^\n]*|/\*[\s\S]*?\*/|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|[A-Za-z_]\w*|\d+(?:\.\d*)?(?:[eE][+-]?\d+)?|::|->|&&|\|\||==|!=|<=|>=|[^\s]')
IDENT = re.compile(r'[A-Za-z_]\w*\Z')
LITERAL = re.compile(r'"([A-Za-z_]\w*)"\Z')
READS = {'lookup', 'lookupOrDefault', 'lookupOrAddDefault'}


def tokens(text):
    return [Token(m.group(), m.start(), m.end()) for m in TOKEN.finditer(text)
            if not m.group().startswith(('//', '/*'))]


def pairs(ts):
    stack = []; result = {}
    closes = {')': '(', ']': '[', '}': '{'}
    for i, t in enumerate(ts):
        if t.value in closes.values():
            stack.append(i)
        elif t.value in closes:
            if not stack or ts[stack[-1]].value != closes[t.value]:
                raise ValueError('unbalanced source delimiters')
            j = stack.pop(); result[j] = i; result[i] = j
    if stack:
        raise ValueError('unbalanced source delimiters')
    return result


def split_args(ts, matched, start, end):
    result = []; left = start; i = start
    while i < end:
        if ts[i].value in ('(', '[', '{'):
            i = matched[i] + 1; continue
        if ts[i].value == ',':
            result.append((left, i)); left = i + 1
        i += 1
    if left < end:
        result.append((left, end))
    return result


def analyze(source, header):
    """Return literal reads, defaults, forwarding and unresolved source uses.

    `complete_local_reads` only describes this syntactic constructor analysis.
    It is never a claim that a model combination is valid or fully specialized.
    """
    result = {'models': [], 'diagnostics': [], 'analysis': 'bounded_cpp_dictionary_v1'}
    ts = tokens(source); hs = tokens(header)
    clean_h = ' '.join(t.value for t in hs)
    classes = re.findall(r'\bclass\s+(\w+)\s*:', clean_h)
    if not classes:
        classes = re.findall(r'\bclass\s+(\w+)\s*\{', clean_h)
    names = re.findall(r'\breturn\s+"(\w+)<"\s*\+', clean_h)
    names += re.findall(r'\bTypeName\s*\(\s*"(\w+)"\s*\)', clean_h)
    if len(set(classes)) != 1 or len(set(names)) != 1:
        result['diagnostics'].append('model_class_or_runtime_name_not_unique')
        return result
    cls = classes[0]; model = names[0]
    base_types=set(re.findall(r'\b(?:public|protected|private)\s+(\w+)',clean_h))
    try:
        matched = pairs(ts)
    except ValueError as exc:
        result['diagnostics'].append(str(exc)); return result
    raw = lambda a, z: source[ts[a].start:ts[z-1].end] if a < z else ''
    span = lambda a, z: {'start': source.count('\n', 0, ts[a].start)+1,
                         'end': source.count('\n', 0, ts[z-1].end)+1,
                         'text': raw(a, z)}

    def signature_dictionary(a, z):
        params = split_args(ts, matched, a, z)
        dictionaries = []
        for n, (p, q) in enumerate(params):
            vals = [t.value for t in ts[p:q]]
            if 'dictionary' in vals and vals[-1:] and IDENT.fullmatch(vals[-1]):
                dictionaries.append((n, vals[-1]))
        return params, dictionaries

    def receiver(i, stop, aliases):
        if ts[i].value not in aliases:
            return None
        dictionary, evidence = aliases[ts[i].value]; j = i + 1
        while j + 3 < stop and [t.value for t in ts[j:j+3]] == ['.', 'subDict', '(']:
            close = matched[j+2]
            if close != j + 4 or not LITERAL.fullmatch(ts[j+3].value):
                return None
            dictionary = '/'.join(x for x in (dictionary, LITERAL.fullmatch(ts[j+3].value).group(1)) if x)
            j = close + 1
        return dictionary, evidence, j

    def lookup(i, stop, aliases, symbolic_keys=()):
        rec = receiver(i, stop, aliases)
        if rec is None:
            return None
        dictionary, evidence, j = rec
        if j+2 >= stop or ts[j].value != '.' or ts[j+1].value not in READS:
            return None
        method = ts[j+1].value; j += 2; value_type = None
        if ts[j].value == '<':
            k = j+1
            while k < stop and ts[k].value != '>':
                k += 1
            if k == stop:
                return None
            value_type = raw(j+1, k); j = k+1
        if j >= stop or ts[j].value != '(':
            return None
        end = matched[j]; args = split_args(ts, matched, j+1, end)
        if not args or args[0][1] != args[0][0]+1:
            return None
        key_token = ts[args[0][0]].value; key_match = LITERAL.fullmatch(key_token)
        if not key_match and key_token not in symbolic_keys:
            return None
        if len(args) != (2 if method != 'lookup' else 1):
            # Optional recursion/pattern flags affect semantics; keep as a gap.
            return None
        fact = {'dictionary': dictionary, 'key': key_match.group(1) if key_match else key_token,
                'method': method, 'value_type': value_type,
                'requirement': 'required' if method == 'lookup' else 'optional',
                'evidence': [span(i, end+1), *evidence]}
        if value_type is None and i>=2 and [t.value for t in ts[i-2:i]]==['readScalar','(']:
            fact['value_type']='scalar'
        if method != 'lookup':
            fact['default_expression'] = raw(*args[1])
            fact['default_kind'] = 'literal' if re.fullmatch(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?|true|false', fact['default_expression']) else 'expression'
        if method == 'lookupOrAddDefault':
            fact['dictionary_effect'] = 'inserts_default_if_absent'
        return fact, end+1

    # Resolve helpers only when their entire body is one dictionary return.
    helpers = {}
    for i, t in enumerate(ts[:-1]):
        if not IDENT.fullmatch(t.value) or ts[i+1].value != '(' or t.value == cls:
            continue
        if i == 0 or ts[i-1].value != '::':
            continue
        close = matched[i+1]; params, dictionaries = signature_dictionary(i+2, close)
        if len(dictionaries) != 1 or close+1 >= len(ts) or ts[close+1].value != '{':
            continue
        # Enclosing qualified class must be this model, not an unrelated helper.
        qualified = ''.join(x.value for x in ts[max(0, i-12):i])
        if not re.search(r'(?:^|::)'+re.escape(cls)+r'(?:<[^<>]+>)?::$', qualified):
            continue
        body = close+1; end = matched[body]
        if body+2 >= end or ts[body+1].value != 'return':
            continue
        dpos, dname = dictionaries[0]
        key_params = {ts[q-1].value: n for n, (p, q) in enumerate(params) if n != dpos}
        found = lookup(body+2, end, {dname: ('', [])}, key_params)
        if found is None:
            continue
        fact, after = found
        if after+1 != end or ts[after].value != ';' or fact['key'] not in key_params:
            continue
        if t.value in helpers:
            helpers[t.value] = None
        else:
            helpers[t.value] = (fact, dpos, key_params[fact['key']], len(params))

    for i, t in enumerate(ts[:-1]):
        if t.value != cls or ts[i+1].value != '(' or i == 0 or ts[i-1].value != '::':
            continue
        close = matched[i+1]; params, dictionaries = signature_dictionary(i+2, close)
        if len(dictionaries) != 1:
            continue
        _, dname = dictionaries[0]; begin = close+1; body = begin
        while body < len(ts) and ts[body].value != '{':
            if ts[body].value in ('(', '['):
                body = matched[body]+1
            elif ts[body].value == ';':
                break
            else:
                body += 1
        if body >= len(ts) or ts[body].value != '{':
            continue
        end = matched[body]; aliases = {dname: ('', [])}
        schema = {'model': model, 'class': cls, 'constructor': span(i, end+1),
                  'dictionary_only_constructor': len(params) == 1,
                  'inputs': [], 'dictionary_forwarding': [], 'unresolved': [],
                  'evidence_status': 'static_syntax', 'runtime_status': 'not_evaluated'}
        if any(x.value == '#' for x in ts[begin:end]):
            schema['unresolved'].append('preprocessor_in_constructor')
            schema['complete_local_reads'] = False
            result['models'].append(schema); continue
        declarations=[j for j in range(body+1,end-2) if ts[j].value=='dictionary' and ts[j+1].value=='&']
        alias_names=[ts[j+2].value for j in declarations]
        if (len(set(alias_names))!=len(alias_names) or dname in alias_names or
                any(any(body < a < j < z < end for a,z in matched.items() if ts[a].value=='{') for j in declarations)):
            schema['unresolved'].append('nested_or_shadowed_dictionary_alias')
            schema['complete_local_reads']=False
            result['models'].append(schema);continue
        initializers = split_args(ts, matched, begin+1, body) if ts[begin].value == ':' else []
        members = []
        for p, q in initializers:
            if p+1 >= q or not IDENT.fullmatch(ts[p].value) or ts[p+1].value != '(':
                schema['unresolved'].append('unsupported_initializer:'+raw(p, q)); continue
            members.append((p, q, ts[p].value))
            args = split_args(ts, matched, p+2, matched[p+1])
            if any(raw(a, z) == dname for a, z in args):
                schema['dictionary_forwarding'].append({'callee': ts[p].value,
                    'dictionary': '', 'relation': 'FORWARDS_DICTIONARY',
                    'callee_kind': 'base' if ts[p].value in base_types else 'unresolved_delegate',
                    'specialization': 'unresolved', 'evidence': span(p, q)})
                if ts[p].value not in base_types:
                    schema['unresolved'].append('unresolved_dictionary_delegate:'+ts[p].value)

        # Track lexical branch regions. No condition is evaluated from source.
        guards = []
        def statement_end(p):
            if p >= end:
                return end
            if ts[p].value == '{':
                return matched[p]+1
            while p < end:
                if ts[p].value in ('(', '[', '{'):
                    p = matched[p]+1; continue
                if ts[p].value == ';':
                    return p+1
                p += 1
            return end
        for j in range(body+1, end):
            if ts[j].value in ('if', 'while', 'for', 'switch') and j+1 < end and ts[j+1].value == '(':
                c = matched[j+1]; z = statement_end(c+1)
                expression = raw(j+2, c)
                guards.append((c+1, z, {'kind': ts[j].value, 'expression': expression, 'branch': 'then'}))
                if z < end and ts[z].value == 'else':
                    guards.append((z+1, statement_end(z+1), {'kind': 'if', 'expression': expression, 'branch': 'else'}))

        covered_dict = set(); j = begin
        while j < end:
            # Const dictionary references, bound only inside this constructor.
            if (ts[j].value == 'dictionary' and j+2 < end and ts[j+1].value == '&'
                    and IDENT.fullmatch(ts[j+2].value)):
                alias = ts[j+2].value; k = j+3
                if k < end and ts[k].value in ('=', '('):
                    rec = receiver(k+1, end, aliases)
                    if rec:
                        path, ev, after = rec
                        if ts[after].value in (';', ')') and not any(a <= j < z for a, z, _ in guards):
                            aliases[alias] = (path, [span(j-1 if ts[j-1].value=='const' else j, after+1), *ev])
                            covered_dict.add(k+1)
            found = lookup(j, end, aliases)
            if found is None and ts[j].value in helpers and helpers[ts[j].value] and ts[j+1].value == '(':
                fact, dpos, kpos, arity = helpers[ts[j].value]
                z = matched[j+1]; args = split_args(ts, matched, j+2, z)
                if len(args) == arity:
                    p, q = args[kpos]; da, dz = args[dpos]
                    rec = receiver(da, dz, aliases)
                    if q == p+1 and LITERAL.fullmatch(ts[p].value) and rec and rec[2] == dz:
                        dictionary, evidence, _ = rec
                        fact = {**fact, 'key': LITERAL.fullmatch(ts[p].value).group(1),
                                'dictionary': '/'.join(x for x in (dictionary, fact['dictionary']) if x),
                                'evidence': [span(j, z+1), *fact['evidence'], *evidence],
                                'via': ts[j].value}
                        covered_dict.add(da); found = fact, z+1
            if found:
                fact, after = found; covered_dict.add(j)
                conditions = [g for a, z, g in guards if a <= j < z]
                owner = next(((p, q, name) for p, q, name in members if p <= j < q), None)
                if owner:
                    p, q, name = owner; fact['member'] = name
                    if any(x.value in ('?', '&&', '||') for x in ts[p:q]):
                        conditions.append({'kind': 'conditional_expression', 'expression': raw(p, q)})
                if conditions:
                    fact['conditions'] = conditions; fact['requirement'] = 'conditional'
                schema['inputs'].append(fact)
                j = after; continue
            j += 1
        for j in range(begin, end):
            if ts[j].value == dname and j not in covered_dict:
                if any(p <= j < q and raw(p, q) == f['evidence']['text'] for p, q, _ in members for f in schema['dictionary_forwarding']):
                    continue
                schema['unresolved'].append({'reason': 'unresolved_dictionary_use', 'evidence': span(j, min(j+6, end))})
        bindings = {f['member']: f['dictionary']+'/'+f['key'] for f in schema['inputs'] if 'member' in f}
        for fact in schema['inputs']:
            if 'default_expression' not in fact:
                continue
            refs = set(re.findall(r'\b[A-Za-z_]\w*\b', fact['default_expression']))
            fact['default_dependencies'] = [bindings[v] for v in sorted(refs & bindings.keys())]
            fact['unresolved_default_symbols'] = sorted(refs - bindings.keys() - {'true', 'false'})
        schema['complete_local_reads'] = not schema['unresolved']
        result['models'].append(schema)
    if not result['models']:
        result['diagnostics'].append('no_supported_dictionary_constructor')
    return result
