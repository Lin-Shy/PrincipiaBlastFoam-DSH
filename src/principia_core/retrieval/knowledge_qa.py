"""Framework-independent, bounded original-source tools for Chapter 2 QA.

The service never accepts annotations, answers, task labels or score-side source
selection. Retrieval backends consume an independently frozen raw corpus.
"""
from __future__ import annotations
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import time
from typing import Protocol

METHODS = {'bm25', 'e5', 'hybrid', 'graph', 'none'}
MANIFEST_SCHEMA = 'independent_blast_knowledge_corpus_v1'

def wire(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)

def digest(value):
    return hashlib.sha256(value).hexdigest()

class FrozenKnowledgeCorpus:
    """Only source paths inside a strict, independently selected raw manifest."""
    def __init__(self, root: Path, manifest: Path):
        self.root = Path(root).resolve()
        self.manifest_path = Path(manifest).resolve()
        raw = self.manifest_path.read_bytes()
        value = json.loads(raw.decode('utf-8'))
        if value.get('schema') != MANIFEST_SCHEMA:
            raise ValueError('independent raw-corpus manifest required; scoring-support manifest rejected')
        if set(value) - {'schema', 'files', 'scope_policy', 'included_roots', 'excluded_extensions', 'selection_implementation_sha256'}:
            raise ValueError('unexpected input fields in raw-corpus manifest')
        if not isinstance(value.get('files'), list) or not value['files']:
            raise ValueError('empty original corpus')
        self.hashes = {}
        for row in value['files']:
            if set(row) != {'path', 'sha256', 'bytes', 'lines'}:
                raise ValueError('raw source metadata whitelist violated')
            name = self.validate_path(row['path'])
            if name in self.hashes:
                raise ValueError('duplicate original source path')
            self.hashes[name] = row['sha256']
        self.manifest_sha256 = digest(raw)
        self.manifest = value

    @staticmethod
    def validate_path(name):
        if not isinstance(name, str) or not name or '\\' in name or ':' in name:
            raise ValueError('original relative path required')
        path = PurePosixPath(name)
        if path.is_absolute() or '..' in path.parts or path.parts[0] not in {'manual', 'tutorials'}:
            raise ValueError('path outside raw source namespace')
        if path.as_posix() != name:
            raise ValueError('noncanonical source path')
        return name

    def lines(self, name):
        name = self.validate_path(name)
        if name not in self.hashes:
            raise ValueError('original source not in frozen manifest')
        target = (self.root / name).resolve()
        if not target.is_relative_to(self.root):
            raise ValueError('resolved source escapes corpus')
        raw = target.read_bytes()
        if digest(raw) != self.hashes[name]:
            raise ValueError('original source hash changed')
        text = raw.decode('utf-8')
        if '\x00' in text:
            raise ValueError('binary source is not an original text passage')
        return text.splitlines()

    def read(self, name, start, end):
        if type(start) is not int or type(end) is not int:
            raise ValueError('integer original line range required')
        lines = self.lines(name)
        if not 1 <= start <= end <= len(lines):
            raise ValueError('invalid original line range')
        return {'path': name, 'sha256': self.hashes[name], 'start': start, 'end': end,
                'lines': [{'number': i, 'text': lines[i-1]} for i in range(start, end+1)]}

class SearchBackend(Protocol):
    def search(self, query: str, limit: int) -> list[dict]: ...

@dataclass(frozen=True)
class KnowledgeBudget:
    tool_calls: int = 8
    tool_characters: int = 6000
    total_characters: int = 24000

    def __post_init__(self):
        if any(type(v) is not int or v <= 0 for v in (self.tool_calls, self.tool_characters, self.total_characters)):
            raise ValueError('positive integer knowledge budgets required')

def tool_specs(method):
    if method not in METHODS:
        raise ValueError('unknown knowledge method')
    if method == 'none':
        return []
    string = {'type': 'string'}
    integer = {'type': 'integer', 'minimum': 1}
    descriptions = {'bm25': 'BM25词项检索', 'e5': 'E5语义检索', 'hybrid': 'BM25与E5混合检索',
                    'graph': '图节点匹配及关系扩展检索'}
    def spec(name, description, properties, required):
        return {'name': name, 'description': description, 'parameters': {
            'type': 'object', 'properties': properties, 'required': required, 'additionalProperties': False}}
    return [spec('catalog', '按公开原始相对路径子串列出文件路径；文件名不构成答案证据。',
                 {'query': string, 'offset': {'type': 'integer', 'minimum': 0}}, ['query']),
            spec('read_source', '读取固定语料指定文件的完整原文行；按next_line续读。',
                 {'path': string, 'start': integer, 'end': integer}, ['path', 'start', 'end']),
            spec('search', descriptions[method] + '；返回带原始路径和行号的证据，可自主补充查询。',
                 {'query': string}, ['query'])]

class KnowledgeToolSession:
    """Same tool envelope and actual delivery budget for every retrieval arm."""
    def __init__(self, method, corpus=None, backend=None, budget=None):
        if method not in METHODS:
            raise ValueError('unknown knowledge method')
        if method == 'none' and (corpus is not None or backend is not None):
            raise ValueError('no-external-knowledge arm must not instantiate corpus/backend')
        if method != 'none' and (not isinstance(corpus, FrozenKnowledgeCorpus) or backend is None):
            raise ValueError('retrieval arm requires frozen raw corpus and isolated backend')
        self.method, self.corpus, self.backend = method, corpus, backend
        self.budget = budget or KnowledgeBudget()
        self.events = []
        self.characters = 0
        self.delivered_lines = set()

    @property
    def available(self):
        return self.method != 'none' and len(self.events) < self.budget.tool_calls and self.characters < self.budget.total_characters

    def _arguments(self, name, args):
        spec = next((t['parameters'] for t in tool_specs(self.method) if t['name'] == name), None)
        if spec is None or not isinstance(args, dict) or set(args) - set(spec['properties']) or not set(spec['required']) <= set(args):
            raise ValueError('tool or argument schema not enabled')
        for key, value in args.items():
            field = spec['properties'][key]
            if field['type'] == 'string':
                if not isinstance(value, str) or len(value) > 2000 or (key != 'query' and not value.strip()):
                    raise ValueError('invalid tool text argument')
            elif type(value) is not int or value < field['minimum']:
                raise ValueError('invalid integer tool argument')
        if name == 'search' and not args['query'].strip():
            raise ValueError('empty retrieval query')

    @staticmethod
    def _fit(payload, cap):
        encoded = wire(payload)
        if len(encoded) <= cap:
            return encoded
        # Keep a valid JSON error if possible; otherwise empty text is the
        # deterministic zero-content tool response. Never cut through JSON.
        minimal = wire({'error': 'knowledge_character_budget_exhausted', 'truncated': True})
        return minimal if len(minimal) <= cap else ''

    def _deliver(self, candidates, cap):
        packet = {'evidence': [], 'truncated': False}
        delivered = []
        for native_rank, candidate in enumerate(candidates, 1):
            # A backend cannot smuggle its own text, scores, graph summaries,
            # or test labels into the answering model's source packet.
            source = self.corpus.read(candidate['path'], candidate['start'], candidate['end'])
            unit = {k: v for k, v in source.items() if k != 'lines'}
            unit.update(rank=native_rank, lines=[])
            original_end = source['end']
            for line in source['lines']:
                proposed = {**unit, 'end': line['number'], 'lines': unit['lines'] + [line]}
                # Reserve truncation/continuation metadata before selecting a line.
                partial = line['number'] < original_end
                if partial:
                    proposed['next_line'] = line['number'] + 1
                trial = {'evidence': packet['evidence'] + [proposed], 'truncated': True}
                if len(wire(trial)) > cap:
                    break
                unit = proposed
                unit.pop('next_line', None)
            if not unit['lines']:
                packet['truncated'] = True
                break
            if unit['end'] < original_end:
                unit['next_line'] = unit['end'] + 1
                packet['truncated'] = True
            packet['evidence'].append(unit)
            delivered.extend((unit['path'], line['number']) for line in unit['lines'])
            if packet['truncated']:
                break
        encoded = self._fit(packet, cap)
        # If even the envelope is replaced by a minimal error, no lines were seen.
        if not encoded or 'evidence' not in json.loads(encoded):
            delivered = []
        return encoded, delivered

    def execute(self, name, args):
        if not self.available:
            raise ValueError('knowledge tools disabled or budget exhausted')
        started = time.monotonic()
        cap = min(self.budget.tool_characters, self.budget.total_characters - self.characters)
        event = {'name': name, 'arguments': args, 'status': 'started', 'delivered_characters': 0}
        self.events.append(event)  # Invalid arguments/actions consume a tool call.
        delivered = []
        try:
            self._arguments(name, args)
            if name == 'catalog':
                matches = [p for p in sorted(self.corpus.hashes) if args['query'].casefold() in p.casefold()]
                offset = args.get('offset', 0)
                kept = []
                for path in matches[offset:]:
                    trial = {'paths': kept + [path], 'offset': offset, 'next_offset': offset + len(kept) + 1,
                             'truncated': True}
                    if len(wire(trial)) > cap:
                        break
                    kept.append(path)
                packet = {'paths': kept, 'offset': offset, 'truncated': offset + len(kept) < len(matches)}
                if packet['truncated']:
                    packet['next_offset'] = offset + len(kept)
                encoded = self._fit(packet, cap)
            elif name == 'read_source':
                encoded, delivered = self._deliver([args], cap)
            else:
                candidates = self.backend.search(args['query'], 10)
                if not isinstance(candidates, list):
                    raise ValueError('retrieval backend returned non-list evidence')
                encoded, delivered = self._deliver(candidates, cap)
            event['status'] = 'returned'
        except (ValueError, KeyError, TypeError, OSError, UnicodeError) as exc:
            event.update(status='tool_error', error_type=type(exc).__name__)
            # Only a bounded classification reaches the model, never filesystem
            # exception text which may reveal paths outside the raw namespace.
            encoded = self._fit({'error': 'invalid_or_unavailable_original_source_or_tool', 'truncated': False}, cap)
        assert len(encoded) <= cap
        event.update(delivered_characters=len(encoded), seconds=time.monotonic()-started,
                     delivered_original_lines=[{'path': p, 'line': n} for p, n in delivered], response=encoded)
        self.characters += len(encoded)
        self.delivered_lines.update(delivered)
        return encoded

    def validate_references(self, references):
        if not isinstance(references, list):
            return False
        for ref in references:
            if not isinstance(ref, dict) or set(ref) != {'path', 'start', 'end'} or not isinstance(ref['path'], str):
                return False
            start, end = ref['start'], ref['end']
            if type(start) is not int or type(end) is not int or not 1 <= start <= end:
                return False
            if any((ref['path'], n) not in self.delivered_lines for n in range(start, end+1)):
                return False
        return True
