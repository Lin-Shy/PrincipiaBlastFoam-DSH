"""将已登记的裁判结构转为无字段间空白的 EBNF；不限制判断标签。"""
import json
from chapter2_qwen_hard_nonthinking import hard_nonthinking_requests


def compact_schema_grammar(schema):
    rules=[];counter=0
    literal=lambda text:json.dumps(text,ensure_ascii=False)
    def visit(node):
        nonlocal counter
        name=f'n{counter}';counter+=1
        if 'const' in node:
            expression=literal(json.dumps(node['const'],ensure_ascii=False,separators=(',',':')))
        elif 'enum' in node:
            if not node['enum']:raise ValueError('Empty semantic choice set')
            expression=' | '.join(literal(json.dumps(v,ensure_ascii=False,separators=(',',':'))) for v in node['enum'])
        elif node['type']=='object':
            properties=node['properties']
            if set(node['required'])!=set(properties) or node.get('additionalProperties') is not False:
                raise ValueError('Only fixed required-key objects are supported')
            parts=[literal('{')]
            for i,(key,value) in enumerate(properties.items()):
                if i:parts.append(literal(','))
                parts.extend([literal(json.dumps(key,ensure_ascii=False)+':'),visit(value)])
            parts.append(literal('}'));expression=' '.join(parts)
        elif node['type']=='array':
            if 'prefixItems' in node:
                items=node['prefixItems']
                if node.get('minItems')!=len(items) or node.get('maxItems')!=len(items):
                    raise ValueError('Actual source segment array must have fixed length')
                parts=[literal('[')]
                for i,item in enumerate(items):
                    if i:parts.append(literal(','))
                    parts.append(visit(item))
                parts.append(literal(']'));expression=' '.join(parts)
            else:
                maximum=node['maxItems']
                if type(maximum) is not int or maximum<0 or node.get('minItems',0)!=0:
                    raise ValueError('Only bounded optional candidate-ID arrays are supported')
                if maximum==0:expression=literal('[]')
                else:
                    item=visit(node['items'])
                    tail='' if maximum==1 else ' ('+literal(',')+' '+item+'){0,'+str(maximum-1)+'}'
                    expression=literal('[')+' ('+item+tail+')? '+literal(']')
        elif node['type']=='string':
            minimum=node.get('minLength',0)
            if minimum not in (0,1):raise ValueError('Unsupported string minimum')
            expression='json-string-nonempty' if minimum else 'json-string'
        else:raise ValueError('Unsupported judge schema node')
        rules.append(name+' ::= '+expression)
        return name
    root=visit(schema)
    return '\n'.join(['root ::= '+root,*rules,
        r'json-string ::= "\"" json-char* "\""',
        r'json-string-nonempty ::= "\"" json-char+ "\""',
        r'json-char ::= [^"\\\x00-\x1f] | "\\" (["\\/bfnrt] | "u" [0-9a-fA-F]{4})'])+'\n'


def compact_grammar_requests(requests):
    result=hard_nonthinking_requests(requests)
    for request in result:
        body=request['body'];schema=body.pop('response_format')['json_schema']['schema']
        body['structured_outputs']={'grammar':compact_schema_grammar(schema)}
    return result
