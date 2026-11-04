"""One explicit compact-JSON grammar and matching validator for all QA models.

The grammar is sent per request, rather than relying on server whitespace
defaults. It describes syntax only and never repairs an assistant response.
"""
from copy import deepcopy
from functools import lru_cache
import json
from models import strict_json

QUERY_LIMIT = 512
CONTRACT = r'''查询query最多512个字符，只写简短检索词，不连续扩写同义词。
每次提交紧凑JSON，字段之间不插入空白；答案、代码字符串内部的正常空格和换行保留。
JSON字符串中的代码双引号写成\"，换行写成\n；反斜杠写成\\。
例如答案含LaTeX的\frac时，JSON字段写成"answer":"\\frac{a}{b}"，不能把反斜杠解码成控制字符。
公式也可以使用Unicode或普通文本。不得输出换页、退格等控制字符。'''


def bounded_specs(specs):
    specs = deepcopy(specs)
    for spec in specs:
        for key, field in spec['parameters']['properties'].items():
            if field.get('type') == 'string':
                # Original specs reuse one dict for query/path. Break aliases.
                field = deepcopy(field)
                field['maxLength'] = QUERY_LIMIT if key == 'query' else 2000
                field['minLength'] = 0 if spec['name'] == 'catalog' and key == 'query' else 1
                spec['parameters']['properties'][key] = field
    return specs


def validate(value, schema, path='$'):
    if 'anyOf' in schema:
        for branch in schema['anyOf']:
            try:
                validate(value, branch, path)
                return
            except ValueError:
                pass
        raise ValueError(path + ': no action schema matches')
    if 'const' in schema:
        if type(value) is not type(schema['const']) or value != schema['const']:
            raise ValueError(path + ': wrong constant')
        return
    kind = schema['type']
    if kind == 'object':
        props = schema['properties']
        if not isinstance(value, dict) or not set(schema['required']) <= set(value) or set(value) - set(props):
            raise ValueError(path + ': wrong fields')
        for key, item in value.items():
            validate(item, props[key], path + '.' + key)
    elif kind == 'array':
        if not isinstance(value, list):
            raise ValueError(path + ': expected array')
        for i, item in enumerate(value):
            validate(item, schema['items'], path + f'[{i}]')
    elif kind == 'string':
        if not isinstance(value, str) or not schema.get('minLength', 0) <= len(value) <= schema.get('maxLength', float('inf')):
            raise ValueError(path + ': string length/type')
        if any((ord(c) < 32 and c not in '\n\r\t') or 0xD800 <= ord(c) <= 0xDFFF for c in value):
            raise ValueError(path + ': abnormal control character or surrogate')
    elif kind == 'integer':
        if type(value) is not int or value < schema.get('minimum', 0):
            raise ValueError(path + ': integer range/type')
    else:
        raise ValueError('Unsupported action schema type')


def diagnostics(content):
    # repr keeps control characters legible without rewriting the response.
    return dict(content_characters=len(content), trailing_spaces=len(content)-len(content.rstrip(' ')),
                suffix_repr=repr(content[-120:]),
                control_characters=[dict(offset=i, codepoint=f'U+{ord(c):04X}')
                                    for i, c in enumerate(content) if ord(c) < 32])


def decode(content, schema):
    value = strict_json(content)
    validate(value, schema)
    in_string = escaped = False
    for c in content:
        if in_string:
            if escaped:
                escaped = False
            elif c == '\\':
                escaped = True
            elif c == '"':
                in_string = False
        elif c == '"':
            in_string = True
        elif c.isspace():
            raise ValueError('Noncompact JSON outside strings')
    return value


def grammar(schema):
    return _grammar(json.dumps(schema, ensure_ascii=False, separators=(',', ':')))


@lru_cache(maxsize=64)
def _grammar(serialized):
    schema = json.loads(serialized)
    rules = []
    literal = lambda s: json.dumps(s, ensure_ascii=False)

    def emit(s):
        name = 'r' + str(len(rules))
        rules.append(None)
        if 'anyOf' in s:
            expr = ' | '.join(emit(branch) for branch in s['anyOf'])
        elif 'const' in s:
            expr = literal(json.dumps(s['const'], ensure_ascii=False))
        elif s['type'] == 'object':
            parts = [literal('{')]
            required = set(s['required'])
            first = True
            for key, field in s['properties'].items():
                piece = ('' if first else literal(',') + ' ') + literal(json.dumps(key) + ':') + ' ' + emit(field)
                if key not in required:
                    if first:
                        raise ValueError('First action field must be required')
                    piece = '(' + piece + ')?'
                else:
                    first = False
                parts.append(piece)
            parts.append(literal('}'))
            expr = ' '.join(parts)
        elif s['type'] == 'array':
            item = emit(s['items'])
            expr = literal('[') + ' (' + item + ' (' + literal(',') + ' ' + item + ')*)? ' + literal(']')
        elif s['type'] == 'string':
            minimum = s.get('minLength', 0)
            maximum = s.get('maxLength')
            repeat = ('{' + str(minimum) + ',' + str(maximum) + '}') if maximum is not None else '+' if minimum == 1 else '*'
            expr = r'"\"" schar' + repeat + r' "\""'
        elif s['type'] == 'integer':
            if s.get('minimum', 0) not in (0, 1):
                raise ValueError('Unsupported integer boundary')
            expr = '[1-9] [0-9]*' if s.get('minimum', 0) == 1 else '("0" | [1-9] [0-9]*)'
        else:
            raise ValueError('Unsupported action grammar')
        rules[int(name[1:])] = name + ' ::= ' + expr
        return name

    root = emit(schema)
    # JSON escapes are preserved as text. No bare control bytes in strings.
    chars = r'schar ::= [^"\\\x00-\x1f] | "\\" (["\\/nrt] | "u" [0-9a-fA-F]{4})'
    return 'root ::= ' + root + '\n' + '\n'.join(rules) + '\n' + chars + '\n'


def configure(body, schema):
    body.pop('response_format', None)
    body['structured_outputs'] = dict(grammar=grammar(schema))
    return body
