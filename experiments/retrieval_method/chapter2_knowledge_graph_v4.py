"""Direct graph scan with selective physical-parent context and honest ablations.

Graph-derived forward fields are cached in RAM, never a term-to-document index,
embedding, external ranker or query/result cache. Raw source bytes are still
verified by the shared source reader. Previous V2/V3 implementations are intact.
"""
from collections import defaultdict, deque
from pathlib import PurePosixPath
import re
import time
import unicodedata

from candidate_graph_utils import tokens
from chapter2_knowledge_graph_retriever import condition_text, present, terms
from chapter2_knowledge_graph_v2 import EvidenceGraphV2, ENGLISH_STOP, PLATFORM_WORDS, RELATION_DECAY
from chapter2_knowledge_graph_v3 import SourceContextGraph, identity_fold


def query_identifiers(query):
    text = identity_fold(query)
    text = re.sub(r'(?<![A-Za-z0-9_])(?:blastfoam|openfoam)(?![A-Za-z0-9_])', ' ', text, flags=re.I)
    text = re.sub(r'场景\s*[a-z](?![A-Za-z0-9_])', ' ', text)
    return set(re.findall(r'[A-Za-z_][A-Za-z0-9_]*', text)) - ENGLISH_STOP - PLATFORM_WORDS - {'yes', 'no', 'true', 'false'}


def accent_fold(text):
    # Tokenization needs the original camel-case boundaries.
    return ''.join(c for c in unicodedata.normalize('NFKD', text) if not unicodedata.combining(c))


class _ForwardGraphScan(EvidenceGraphV2):
    """An alternative base scan for SourceContextGraph's identity rescoring.

    The multiple-inheritance order intentionally places this between the source
    identity layer and EvidenceGraphV2; it changes field preparation, not the
    graph-only retrieval boundary. Every query still scans every allowed node.
    """
    def _facet_flat(self, query):
        distinctive = accent_fold(query)
        distinctive = re.sub(r'(?<![A-Za-z0-9_])(?:blastfoam|openfoam)(?![A-Za-z0-9_])', ' ', distinctive, flags=re.I)
        distinctive = re.sub(r'场景\s*[a-z](?![A-Za-z0-9_])', ' ', distinctive, flags=re.I)
        identifiers = query_identifiers(query)
        qt = set(tokens(distinctive)) - PLATFORM_WORDS - ENGLISH_STOP
        english = {t for t in qt if t.isascii()} | identifiers
        chinese = qt - english
        weights = {t: 2 if t in identifiers else 1 for t in english}
        cases, manual_only, tutorial_only = self._scope(query)
        rows = []; scanned = filtered = navigation = 0
        for nid, fields in self._forward.items():
            node = self.nodes[nid]
            if not self._allowed(node, cases, manual_only, tutorial_only):
                filtered += 1; continue
            if fields['boilerplate']:continue
            if fields['navigation']:
                navigation += 1; continue
            scanned += fields['characters']
            nt = fields['terms']; headings = fields['heading_terms']
            hits = english & nt; context_hits = english & headings; cn = chinese & nt
            path_match = bool(fields['path_terms'] & identifiers)
            if not hits and not context_hits and not cn and not path_match:continue
            lexical = 30 * sum(weights[t] for t in hits) / max(1, sum(weights.values()))
            lexical += 8 * len(cn) / max(1, len(chinese))
            lexical += 8 * sum(weights[t] for t in context_hits) / max(1, sum(weights.values()))
            condition_overlap = len(qt & fields['condition_terms'])
            score = lexical + 4 * (bool(fields['identity']) and fields['identity'] in identifiers)
            score += 4 * (bool(fields['key']) and fields['key'] in identifiers)
            score += 2 * path_match + 4 * (fields['case'] in cases if fields['case'] else False)
            score += min(2, condition_overlap)
            rows.append(dict(node_id=nid, score=score, origin=nid, visited=[nid], route=[], reasons=dict(
                technical_identifier_overlap=sorted(hits), chinese_overlap=len(cn), source_heading_overlap=sorted(context_hits),
                exact_identity_match=fields['identity'] in identifiers, condition_overlap=condition_overlap)))
        rows.sort(key=lambda r: (-r['score'], r['node_id']))
        return dict(items=rows, diagnostic=dict(seeds=rows[:self.options['seed_limit']],
            graph_field_characters_scanned=scanned, scope_filtered_nodes=filtered, navigation_only_nodes_excluded=navigation,
            external_index_loaded=False, model_calls=0, rank_is_before_character_budget=True,
            forward_graph_fields_cached=True, query_or_result_cache=False,
            source_owners=len({n['owner'] for n in self.nodes.values()}), seed_policy='forward_graph_fields_v4'))


class AdaptiveSourceGraph(SourceContextGraph, _ForwardGraphScan):
    def __init__(self, *args, context_policy='adaptive', parent_ratio=.5, context_seed_limit=10, **kwargs):
        if context_policy not in {'adaptive', 'adjacent', 'blanket', 'none'}:
            raise ValueError('Unknown physical source context policy')
        if type(parent_ratio) not in (float, int) or not 0 <= parent_ratio < 1:
            raise ValueError('Parent threshold must be in [0,1)')
        if type(context_seed_limit) is not int or context_seed_limit < 1:
            raise ValueError('Positive context seed limit required')
        super().__init__(*args, **kwargs)
        self.context_policy = context_policy; self.parent_ratio = parent_ratio; self.context_seed_limit = context_seed_limit
        self._forward = {}
        for nid, node in self.nodes.items():
            unit = self.graph['units'][node['unit_id']]
            text = ' '.join(str(node.get(k) or '') for k in ('label', 'name', 'subject', 'owner_model', 'key', 'value', 'dictionary', 'body'))
            text += ' ' + ' '.join(node.get('aliases', []))
            headings = [c['title'] for c in unit.get('context', [])]
            self._forward[nid] = dict(terms=frozenset(tokens(accent_fold(text))),
                heading_terms=frozenset(tokens(accent_fold(' '.join(headings)))), path_terms=frozenset(tokens(node['path'])),
                identity=identity_fold(str(node.get('name') or node.get('owner_model') or '')),
                key=identity_fold(str(node.get('key') or '')), characters=len(text),
                condition_terms=frozenset(tokens(condition_text(node.get('conditions', [])))) if self.options['with_conditions'] else frozenset(),
                case=unit.get('source_context', {}).get('case_directory'), boilerplate=node.get('dictionary', '').startswith('FoamFile'),
                navigation=any(re.fullmatch(r'(?:table of )?contents|目录', h.strip(), re.I) for h in headings))

    def _scope(self, query):
        cases = {case for case, aliases in self.case_aliases.items() if any(present(query, alias) for alias in aliases)}
        return cases, '手册' in query and '教程' not in query and not cases, '只查教程' in query or '仅查教程' in query

    def _allowed(self, node, cases, manual_only, tutorial_only):
        path = node['path']; case = self.graph['units'][node['unit_id']].get('source_context', {}).get('case_directory')
        return not ((cases and case and case not in cases) or (manual_only and path.startswith('tutorials/'))
                    or (tutorial_only and path.startswith('manual/')))

    def _facet_flat(self, query):
        flat = super()._facet_flat(query)
        # V3 suppressed a static graph-field seed bonus in no-extension mode.
        # Preserve identical flat seeds when the edge traversal alone is off.
        if self.identity_ranking and self.options['with_cross'] and not self.options['with_paths']:
            count = max(1, len(query_identifiers(query)))
            for row in flat['items']:
                keys = row['reasons'].get('parent_declared_key_overlap', [])
                bonus = 12 * len(keys) / count if len(keys) >= 2 else 0
                row['score'] += bonus
                row['reasons']['parent_declaration_bonus'] = bonus
            flat['items'].sort(key=lambda r: (-r['score'], self.nodes[r['node_id']]['path'],
                self.graph['units'][self.nodes[r['node_id']]['unit_id']]['start'], r['node_id']))
            flat['diagnostic']['seeds'] = flat['items'][:self.options['seed_limit']]
        return flat

    def rank(self, query):
        started = time.monotonic(); flat = self._facet_flat(query); seeds = flat['diagnostic']['seeds']
        best = {r['node_id']: dict(r) for r in flat['items']}; frontier = seeds; expanded = 0
        cases, manual_only, tutorial_only = self._scope(query); qt = terms(query)
        if self.options['with_paths']:
            for _ in range(self.options['depth']):
                following = []
                for row in frontier:
                    for target, edge, direction in self.adjacency[row['node_id']]:
                        decay = RELATION_DECAY.get(edge['relation'])
                        if decay is None or target in row['visited']:continue
                        if edge['relation'] == 'FILE_SELECTOR_CONTEXT' and direction != 'forward':continue
                        node = self.nodes[target]
                        if not self._allowed(node, cases, manual_only, tutorial_only):continue
                        if edge['relation'] == 'SOURCE_SECTION_PARENT' and not qt & terms(' '.join(str(node.get(k) or '') for k in ('label', 'name', 'body'))):continue
                        expanded += 1; score = row['score'] * decay
                        route = row['route'] + [dict(edge_id=edge['id'], relation=edge['relation'], direction=direction,
                            cross_owner=edge['cross_owner'], conditions=edge.get('conditions', []), condition_evaluated=False)]
                        candidate = dict(node_id=target, score=score, origin=row['origin'], visited=row['visited'] + [target],
                            route=route, reasons=dict(typed_route=True, decay=decay))
                        if target not in best or score > best[target]['score']:
                            best[target] = candidate; following.append(candidate)
                frontier = sorted(following, key=lambda r: (-r['score'], r['node_id']))[:self.options['seed_limit']]
        units = {}
        for row in best.values():
            uid = self.nodes[row['node_id']]['unit_id']
            if uid not in units or (row['score'], row['node_id']) > (units[uid]['score'], units[uid]['node_id']):units[uid] = row
        candidates = list(units.values()); native = []; path_counts = defaultdict(int)
        while candidates and len(native) < self.options['native_limit']:
            row = min(candidates, key=lambda r: (-r['score'] / (1 + .25 * path_counts[self.nodes[r['node_id']]['path']]), r['node_id']))
            candidates.remove(row); node = self.nodes[row['node_id']]; path_counts[node['path']] += 1
            native.append({**row, 'native_rank': len(native) + 1, 'path': node['path'], 'owner': node['owner'],
                'anchors': node['evidence'], 'conditions': node.get('conditions', []) if self.options['with_conditions'] else []})
        return dict(schema='adaptive_source_context_graph_v4', items=native, options=dict(self.options), graph_sha256=self.graph_sha256,
            diagnostic={**flat['diagnostic'], 'expanded_edges': expanded, 'graph_scan_seconds_and_ranking': time.monotonic() - started,
                'cross_owner_additive_bonus': 0, 'ranked_unique_source_units': len(units), 'evidence_policy': 'owned_original_context',
                'context_policy': self.context_policy, 'context_characters': self.context_characters,
                'parent_ratio_strictly_greater_than': self.parent_ratio, 'context_seed_limit': self.context_seed_limit})

    def _bridge(self, source, target, parent):
        if source == target:return []
        for dest, edge, direction in self.adjacency[source]:
            if dest == target and edge['relation'] == 'SOURCE_PARENT_CONTEXT' and edge.get('support', {}).get('container_id') == parent['id']:
                return [dict(edge_id=edge['id'], relation=edge['relation'], direction=direction, cross_owner=edge['cross_owner'], container_id=parent['id'])]
        raise ValueError('Physical parent context lacks an allowed source-owned edge')

    def _select_context(self, row, hits):
        uid = self.nodes[row['node_id']]['unit_id']; unit = self.graph['units'][uid]
        selected = {uid: unit}; routes = {uid: []}; decisions = []
        if not self.options['with_paths'] or not self.context_characters or self.context_policy == 'none':return selected, routes, decisions
        if self.context_policy == 'blanket':
            selected, routes = super()._context(row)
            return selected, routes, [dict(policy='blanket_physical_parents_and_ancestor_introductions')]
        if self.context_policy == 'adaptive':
            parents = [self.graph['source_containers'][cid] for cid in unit.get('parent_context_ids', [])]
            for parent in sorted(parents, key=lambda p: (p['characters'], p['start'])):
                members = [self.graph['units'][k] for k in parent['members']]
                ratio = len(hits & set(parent['members'])) / len(members)
                eligible = len(members) > 1 and ratio > self.parent_ratio and parent['characters'] <= self.context_characters
                if not self.options['with_cross'] and any(v['owner'] != unit['owner'] for v in members):eligible = False
                decisions.append(dict(container_id=parent['id'], hit_fraction=ratio, members=len(members), eligible=eligible))
                if not eligible:continue
                representative = self.raw_nodes[parent['members'][0]]
                for v in members:
                    selected[v['id']] = v
                    routes[v['id']] = self._bridge(self.raw_nodes[uid], representative, parent) + self._bridge(representative, self.raw_nodes[v['id']], parent) if v['id'] != uid else []
                break
        used = sum(len(v['text']) for v in selected.values()); frontier = deque((self.raw_nodes[k], routes[k]) for k in selected)
        while frontier:
            current, route = frontier.popleft()
            for target, edge, direction in sorted(self.adjacency[current], key=lambda e: self.graph['units'][self.nodes[e[0]]['unit_id']]['start']):
                if edge['relation'] != 'SOURCE_NEXT_FRAGMENT':continue
                other = self.nodes[target]; v = self.graph['units'][other['unit_id']]
                if v['id'] in selected or v['path'] != unit['path'] or used + len(v['text']) > self.context_characters:continue
                if re.search(r'"key"\s*:\s*"FoamFile"', v['owner_key']):continue
                if any(c['title'].strip().casefold() in {'contents', 'table of contents', '目录'} for c in v.get('context', [])):continue
                used += len(v['text']); selected[v['id']] = v
                routes[v['id']] = route + [dict(edge_id=edge['id'], relation=edge['relation'], direction=direction, cross_owner=edge['cross_owner'])]
                frontier.append((target, routes[v['id']]))
        return selected, routes, decisions

    def read_native(self, ranking):
        hits = {self.nodes[r['node_id']]['unit_id'] for r in ranking['items'][:self.context_seed_limit]}
        items = []; seen = set()
        for row in ranking['items']:
            uid = self.nodes[row['node_id']]['unit_id']; selected, routes, decisions = self._select_context(row, hits)
            fresh = [v for k, v in selected.items() if k not in seen]
            if not fresh:continue
            # Always deliver the located fragment before surrounding material.
            fresh.sort(key=lambda v: (v['id'] != uid, v['start'])); ranges = []
            for v in fresh:
                if ranges and ranges[-1]['end'] + 1 == v['start']:ranges[-1]['end'] = v['end']
                else:ranges.append(dict(start=v['start'], end=v['end']))
                seen.add(v['id'])
            items.append(dict(path=row['path'], ranges=ranges, native_unit=row['node_id'], native_rank=row['native_rank'],
                owner=row['owner'], original_sha256=self.hashes[row['path']], read_policy='located_original_first_then_selected_physical_context',
                context_policy=self.context_policy, parent_decisions=decisions,
                context_fragments=[dict(unit_id=v['id'], owner=v['owner'], start=v['start'], end=v['end'], route=routes[v['id']]) for v in fresh]))
        return dict(items=items, ranking_diagnostic=ranking['diagnostic'], native_ranking=ranking)
