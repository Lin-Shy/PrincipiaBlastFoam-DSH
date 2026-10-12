"""同一原文单元上的词法、章节上下文与一跳语义补充检索。"""
from __future__ import annotations

import argparse
import copy
from collections import Counter, defaultdict
import json
import math
from pathlib import Path
import re

import manual_graph as g
from knowledge import tokens


class ManualSearch:
    def __init__(self, graph, semantic=None, review=None):
        self.graph = graph; self.semantic = semantic
        self.byid = {n['id']: n for n in graph['nodes']}
        self.units = [n for n in graph['nodes'] if n['kind'] == 'evidence' and not n['path'].startswith('00_')]
        self.tf = {}; self.df = Counter(); self.facts = []; self.byentity = defaultdict(list)
        for u in self.units:
            section = self.byid[u['section']]
            tf = Counter(tokens(' '.join(section['hierarchy'])+' '+u['markdown']))
            self.tf[u['id']] = tf; self.df.update(tf.keys())
        self.average = sum(sum(tf.values()) for tf in self.tf.values()) / max(1, len(self.tf))
        rejected = {r['fact'] for r in (review or {}).get('decisions', []) if r['status'] == 'reject'}
        decisions = {r['fact']: r for r in (review or {}).get('decisions', [])}
        if semantic:
            if semantic['foundation_snapshot'] != graph['snapshot']:
                raise ValueError('semantic/foundation mismatch')
            if review and review.get('semantic_snapshot') != semantic['snapshot']:
                raise ValueError('semantic review mismatch')
            self.facts = [copy.deepcopy(f) for f in semantic['facts'] if f['id'] not in rejected]
            for f in self.facts:
                decision = decisions.get(f['id'])
                if decision:
                    f['review'] = decision['status'] + '_by_source_review'
                    for uid in decision.get('additional_source_units', []):
                        n = self.byid[uid]
                        if n['kind'] != 'evidence' or n['section'] != f['section']:
                            raise ValueError('review source outside fact section')
                        f['evidence'].append({'source': uid, 'path': n['path'], 'sha256': n['sha256'],
                                              'line_start': n['start'], 'line_end': n['end'], 'quote': n['markdown']})
                for e in (f['subject'], f['object']):
                    self.byentity[e['id']].append(f)

    def ranked(self, query):
        terms = sorted(set(tokens(query))); scores = []
        for u in self.units:
            tf = self.tf[u['id']]; length = sum(tf.values()); score = 0
            for t in terms:
                count = tf[t]
                if count:
                    idf = math.log(1+(len(self.units)-self.df[t]+.5)/(self.df[t]+.5))
                    score += idf * count*2.2/(count+1.2*(.25+.75*length/self.average))
            if score:
                scores.append((score, u['id']))
        return sorted(scores, key=lambda x: (-x[0], self.byid[x[1]]['path'], self.byid[x[1]]['start']))

    def source_units(self, source):
        node = self.byid[source]
        if node['kind'] == 'evidence':
            return [source]
        if node['kind'] == 'section':
            return node['units']
        return []

    def expand_section(self, seed):
        unit = self.byid[seed]; s = self.byid[unit['section']]
        candidates = [(u, {'relation': 'SAME_SECTION', 'seed': seed}) for u in s['units']]
        for e in self.graph['edges']:
            if e['source'] == seed and e['relation'] in ('REFERS_TO_SECTION', 'REFERS_TO_FORMULA'):
                candidates += [(u, {'relation': e['relation'], 'seed': seed}) for u in self.source_units(e['target'])]
        parent = self.byid[s['parent']]
        if parent['kind'] == 'section':
            candidates += [(u, {'relation': 'PARENT_CONTEXT', 'seed': seed}) for u in parent['units']]
        return candidates

    def expand_semantic(self, seed, query):
        seed_section = self.byid[seed]['section']
        # 从已召回原文中的事实出发，只跨一个共享实体，不全图泛化条件。
        start = [f for f in self.facts if any(e['source'] == seed for e in f['evidence']) or f['section'] == seed_section]
        query_terms = set(tokens(query))
        matched = {}
        for f in start:
            for entity in (f['subject'], f['object']):
                entity_terms = set(tokens(entity['name']))
                if not entity_terms & query_terms:
                    continue
                for related in self.byentity[entity['id']]:
                    matched[related['id']] = (related, entity['id'])
        candidates = []
        ordered = sorted(matched.values(), key=lambda pair: (
            -len(set(tokens(pair[0]['subject']['name']+' '+pair[0]['object']['name'])) & query_terms), pair[0]['id']))
        for f, entity_id in ordered:
            via = {'relation': f['relation'], 'seed': seed, 'fact': f['id'], 'entity': entity_id,
                   'conditions_zh': f['conditions_zh'], 'review': f['review']}
            for ev in f['evidence']:
                candidates += [(u, via) for u in self.source_units(ev['source'])]
            # 实体定义所在小节用于补充主体/客体含义，不把整章展开。
            for entity in (f['subject'], f['object']):
                candidates += [(u, {**via, 'role': 'entity_definition'}) for u in self.source_units(entity['scope'])]
        # 明示章节引用也是图关系，三个策略中的章节组同样可使用。
        for e in self.graph['edges']:
            if e['source'] == seed and e['relation'] in ('REFERS_TO_SECTION', 'REFERS_TO_FORMULA'):
                candidates += [(u, {'relation': e['relation'], 'seed': seed}) for u in self.source_units(e['target'])]
        return candidates

    def chunk(self, uid, ordinal):
        u = self.byid[uid]; s = self.byid[u['section']]
        return f"### [E{ordinal}] {' > '.join(s['hierarchy'])}\n{u['path']}:{u['start']}-{u['end']}\n\n{u['markdown']}\n"

    def protected_lexical(self, query, ranked, budget):
        """先模拟完整词法包，保护其预算内前缀及查询明确点名的小节。"""
        baseline = []; size = 0
        for _, uid in ranked:
            cost = len(self.chunk(uid, len(baseline)+1))
            if size+cost <= budget:
                baseline.append(uid); size += cost
        protected = set(); reserved = 0; query_terms = set(tokens(query))
        term_sources = defaultdict(list)
        for uid in baseline:
            for term in query_terms & self.tf[uid].keys():
                term_sources[term].append(uid)
        for uid in baseline:
            cost = len(self.chunk(uid, len(protected)+1))
            if not protected or reserved+cost <= int(budget*.6):
                protected.add(uid); reserved += cost
        for uid in baseline:
            title = self.byid[self.byid[uid]['section']]['label']
            title = re.sub(r'^\d+(?:\.\d+)*\s+', '', title)
            title = re.sub(r'\s*\[[^\]]*\]\s*$', '', title).strip('` ')
            if re.fullmatch(r'[A-Za-z][A-Za-z0-9_+]*(?:/[A-Za-z][A-Za-z0-9_+]*)*', title):
                if {name.casefold() for name in title.split('/')} <= query_terms:
                    protected.add(uid)
        # 某个查询词只有一份已召回来源支持时，扩展不能删除这份唯一依据。
        for matches in term_sources.values():
            if len(matches) == 1:
                protected.add(matches[0])
        return [uid for uid in baseline if uid in protected]

    def search(self, query, strategy='text', budget=6000):
        if strategy not in ('text', 'sections', 'semantic') or budget < 256:
            raise ValueError('invalid strategy/budget')
        if strategy == 'semantic' and self.semantic is None:
            raise ValueError('semantic graph required')
        ranked = self.ranked(query)
        order = []; seen = set()
        def add(uid, via):
            if uid not in seen:
                seen.add(uid); order.append((uid, via))
        scores = dict((uid, score) for score, uid in ranked)
        protected = self.protected_lexical(query, ranked, budget) if strategy != 'text' else []
        for uid in protected:
            add(uid, {'relation': 'LEXICAL', 'score': scores[uid], 'protected': True})
        # 仅从已保证装入的词法来源扩展；每个种子最多补充两个单元。
        for seed in protected[:3]:
            expansions = self.expand_section(seed) if strategy == 'sections' else self.expand_semantic(seed, query) if strategy == 'semantic' else []
            added = 0
            for uid, via in expansions:
                if uid in seen:
                    continue
                add(uid, via); added += 1
                if added == 2:
                    break
        for score, uid in ranked:
            add(uid, {'relation': 'LEXICAL', 'score': score})
        output = ''; selected = []; omitted = []
        for uid, via in order:
            u = self.byid[uid]; s = self.byid[u['section']]
            label = f'E{len(selected)+1}'
            chunk = self.chunk(uid, len(selected)+1)
            if len(output+chunk) > budget:
                omitted.append({'unit': uid, 'reason': 'budget', 'characters': len(chunk)}); continue
            output += chunk
            selected.append({'label': label, 'unit': uid, 'via': via, 'path': u['path'],
                             'start': u['start'], 'end': u['end'], 'sha256': u['sha256']})
        if not set(protected) <= {x['unit'] for x in selected}:
            raise AssertionError('protected lexical evidence was displaced')
        return {'strategy': strategy, 'query': query, 'budget_characters': budget,
                'protected_lexical': protected, 'lexical_reserve_fraction': .6,
                'foundation_snapshot': self.graph['snapshot'],
                'semantic_snapshot': self.semantic['snapshot'] if strategy == 'semantic' else None,
                'markdown': output, 'characters': len(output), 'selected': selected, 'omitted': omitted,
                'status': 'ok' if selected else 'no_evidence_fits',
                'limits': ['预算约束返回Markdown；审计字段不送入回答模型', '原文完整不表示回答所需依据完整']}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--foundation', type=Path, required=True)
    p.add_argument('--semantic', type=Path)
    p.add_argument('--review', type=Path)
    p.add_argument('--source', type=Path, default=g.ROOT/'corpus/manual/markdown')
    p.add_argument('--query', required=True)
    p.add_argument('--strategy', choices=['text', 'sections', 'semantic'], default='text')
    p.add_argument('--budget', type=int, default=6000)
    p.add_argument('--audit', type=Path)
    args = p.parse_args()
    graph = json.loads(args.foundation.read_text()); g.validate(graph, args.source)
    semantic = json.loads(args.semantic.read_text()) if args.semantic else None
    review = json.loads(args.review.read_text()) if args.review else None
    packet = ManualSearch(graph, semantic, review).search(args.query, args.strategy, args.budget)
    if args.audit:
        g.write(args.audit, packet)
    print(packet['markdown'])
