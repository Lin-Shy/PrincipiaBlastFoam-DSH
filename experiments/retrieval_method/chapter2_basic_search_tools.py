"""Ordinary glob/grep/read tools over the independent frozen raw corpus.

No graph, aliases, token ranking, embeddings, or persistent search index.
Path/line ordering is deterministic rather than a relevance score.
"""
from fnmatch import fnmatchcase
import json
import time
import regex
from principia_core.retrieval.knowledge_qa import KnowledgeToolSession, KnowledgeBudget, FrozenKnowledgeCorpus, wire


def basic_specs():
    string = {'type': 'string'}
    integer = {'type': 'integer', 'minimum': 1}
    def spec(name, description, properties, required):
        return dict(name=name, description=description, parameters=dict(type='object', properties=properties,
            required=required, additionalProperties=False))
    return [
        spec('glob', '用普通glob通配符查找固定资料中的文件路径，如**/*controlDict或manual/**/*.md；按路径排序，不进行相关性排序。offset用于翻页；文件名不是答案证据。',
             dict(pattern=string, offset={'type': 'integer', 'minimum': 0}), ['pattern']),
        spec('grep', '用普通逐行正则表达式搜索固定资料原文，如JWL|MieGruneisen；默认区分大小写，可用(?i)忽略大小写。可用include限定文件glob；按路径、行号排序，不做语义扩展或相关性排序。返回命中原文行及行号，offset用于翻页；上下文请用read_source读取。',
             dict(pattern=string, include=string, offset={'type': 'integer', 'minimum': 0}), ['pattern']),
        spec('read_source', '读取固定语料指定文件的完整原文行；按next_line续读。',
             dict(path=string, start=integer, end=integer), ['path', 'start', 'end'])]


def path_matches(path, pattern):
    """Slash-aware glob: * one component, ** zero or more components."""
    if not pattern or pattern.startswith('/') or '\\' in pattern or ':' in pattern or '..' in pattern.split('/'):
        raise ValueError('Relative positive corpus glob required')
    if '/' not in pattern:
        return fnmatchcase(path.rsplit('/', 1)[-1], pattern)
    names, parts = path.split('/'), pattern.split('/')
    def match(i, j):
        if j == len(parts):
            return i == len(names)
        if parts[j] == '**':
            return match(i, j+1) or (i < len(names) and match(i+1, j))
        return i < len(names) and fnmatchcase(names[i], parts[j]) and match(i+1, j+1)
    return match(0, 0)


class BasicSearchSession(KnowledgeToolSession):
    def __init__(self, corpus, budget=None):
        if not isinstance(corpus, FrozenKnowledgeCorpus):
            raise ValueError('Independent original corpus required')
        self.method, self.corpus, self.backend = 'basic_search', corpus, None
        self.budget = budget or KnowledgeBudget()
        self.events, self.characters, self.delivered_lines = [], 0, set()

    def _arguments(self, name, args):
        spec = next((s['parameters'] for s in basic_specs() if s['name'] == name), None)
        if spec is None or not isinstance(args, dict) or set(args)-set(spec['properties']) or not set(spec['required']) <= set(args):
            raise ValueError('Disabled tool or argument')
        for key, value in args.items():
            field = spec['properties'][key]
            if field['type'] == 'string':
                if not isinstance(value, str) or not value.strip() or len(value) > 2000:
                    raise ValueError('Invalid text')
            elif type(value) is not int or value < field['minimum']:
                raise ValueError('Invalid integer')

    def execute(self, name, args):
        if not self.available:
            raise ValueError('Tool budget exhausted')
        started = time.monotonic()
        cap = min(self.budget.tool_characters, self.budget.total_characters-self.characters)
        event = dict(name=name, arguments=args, status='started', delivered_characters=0)
        self.events.append(event)
        delivered = []
        try:
            self._arguments(name, args)
            if name == 'read_source':
                encoded, delivered = self._deliver([args], cap)
            elif name == 'glob':
                matches = [p for p in sorted(self.corpus.hashes) if path_matches(p, args['pattern'])]
                offset, kept = args.get('offset', 0), []
                for path in matches[offset:]:
                    if len(wire(dict(paths=kept+[path], offset=offset, next_offset=offset+len(kept)+1, truncated=True))) > cap:
                        break
                    kept.append(path)
                packet = dict(paths=kept, offset=offset, truncated=offset+len(kept)<len(matches))
                if packet['truncated']:
                    packet['next_offset'] = offset+len(kept)
                encoded = self._fit(packet, cap)
            else:
                expression = regex.compile(args['pattern'])
                candidates = []
                for path in sorted(self.corpus.hashes):
                    if not path_matches(path, args.get('include', '**/*')):
                        continue
                    for n, line in enumerate(self.corpus.lines(path), 1):
                        if expression.search(line, timeout=.05):
                            candidates.append(dict(path=path, start=n, end=n))
                    if time.monotonic()-started > 10:
                        raise TimeoutError('Grep scan timeout')
                offset = args.get('offset', 0)
                # _deliver retains complete raw lines under the shared cap.
                # Reserve pagination metadata so continuation cannot hide text.
                encoded, delivered = self._deliver(candidates[offset:], max(0, cap-100))
                packet = json.loads(encoded) if encoded else {}
                if 'evidence' in packet:
                    consumed = len(packet['evidence'])
                    packet.update(offset=offset, truncated=offset+consumed<len(candidates))
                    if packet['truncated']:
                        packet['next_offset'] = offset+consumed
                    encoded = self._fit(packet, cap)
                    if not encoded or 'evidence' not in json.loads(encoded):
                        delivered = []
            event['status'] = 'returned'
        except (ValueError, KeyError, TypeError, OSError, UnicodeError, regex.error, TimeoutError) as exc:
            event.update(status='tool_error', error_type=type(exc).__name__)
            encoded = self._fit(dict(error='invalid_or_unavailable_original_source_or_tool', truncated=False), cap)
            delivered = []
        assert len(encoded) <= cap
        event.update(delivered_characters=len(encoded), seconds=time.monotonic()-started,
            delivered_original_lines=[dict(path=p, line=n) for p,n in delivered], response=encoded)
        self.characters += len(encoded)
        self.delivered_lines.update(delivered)
        return encoded
