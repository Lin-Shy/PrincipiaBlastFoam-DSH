"""从完整 Markdown 构建章节与原文证据图；不改写语料、不调用模型。"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = 'manual-evidence-v1'


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def sha(value):
    return hashlib.sha256(value if isinstance(value, bytes) else value.encode()).hexdigest()


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(encoded(value) + '\n')
    temporary.replace(path)


def inventory(root):
    return {p.relative_to(root).as_posix(): sha(p.read_bytes())
            for p in sorted(root.rglob('*')) if p.is_file()}


def atoms(lines, start=0, stop=None):
    """识别原子块，区间为零基半开；空白跟随前块，重组逐字等于原文。"""
    stop = len(lines) if stop is None else stop
    result = []
    i = start
    while i < stop:
        a = i
        s = lines[i].strip()
        fence = re.match(r'^(`{3,}|~{3,})', s)
        if not s:
            kind = 'space'; i += 1
        elif fence:
            kind = 'code'; marker = fence[1]; i += 1
            while i < stop and not re.match(r'^' + re.escape(marker[0]) + '{' + str(len(marker)) + r',}\s*$', lines[i].strip()):
                i += 1
            if i == stop:
                raise ValueError(f'unclosed code fence at line {a+1}')
            i += 1
        elif s.startswith('$$'):
            kind = 'formula'; i += 1
            if s.count('$$') < 2:
                while i < stop and '$$' not in lines[i]:
                    i += 1
                if i == stop:
                    raise ValueError(f'unclosed math at line {a+1}')
                i += 1
            # 单独放在显示公式后的编号属于公式，不是一个新段落。
            j = i
            while j < stop and not lines[j].strip():
                j += 1
            if j < stop and re.fullmatch(r'\(\d+\.\d+[a-z]?\)', lines[j].strip()):
                i = j + 1
        elif re.match(r'^#{1,6}\s+', s):
            kind = 'heading'; i += 1
        elif s.startswith('|'):
            kind = 'table'; i += 1
            while i < stop and lines[i].strip().startswith('|'):
                i += 1
        elif s.startswith('>'):
            kind = 'note'; i += 1
            while i < stop and lines[i].strip().startswith('>'):
                i += 1
        elif re.match(r'^!\[', s):
            kind = 'figure'; i += 1
        else:
            kind = 'text'; i += 1
            while i < stop and lines[i].strip() and not re.match(r'^(?:#{1,6}\s|```|~~~|\$\$|\||>|!\[)', lines[i].strip()):
                i += 1
        while i < stop and not lines[i].strip():
            i += 1
        result.append({'kind': kind, 'start': a, 'end': i})
    return result


def evidence_groups(blocks, lines, short_limit=2400):
    if not blocks:
        return []
    size = lambda bs: sum(len(''.join(lines[b['start']:b['end']])) for b in bs)
    if size(blocks) <= short_limit:
        return [blocks]
    groups = []
    i = 0
    while i < len(blocks):
        group = [blocks[i]]; i += 1
        # 公式的引导句、连续公式和 where 定义不因预算切断。
        if group[0]['kind'] == 'text' and i < len(blocks) and blocks[i]['kind'] == 'formula':
            group.append(blocks[i]); i += 1
        if any(b['kind'] == 'formula' for b in group):
            while i < len(blocks):
                b = blocks[i]; text = ''.join(lines[b['start']:b['end']]).strip()
                continuation = b['kind'] == 'formula' or (b['kind'] == 'text' and
                    (re.match(r'^(where\b|and\b|with\b)', text, re.I) or len(text) < 35))
                if not continuation:
                    break
                group.append(b); i += 1
        groups.append(group)
    return groups


def build(root=ROOT/'corpus/manual/markdown'):
    root = Path(root)
    hashes = inventory(root)
    nodes = []; edges = []; warnings = []
    files = sorted(root.glob('*.md'))
    if not files:
        raise ValueError('no Markdown source files')
    for path in files:
        rel = path.relative_to(root).as_posix()
        text = path.read_bytes().decode('utf-8'); lines = text.splitlines(keepends=True)
        parts = atoms(lines)
        headings = [b for b in parts if b['kind'] == 'heading']
        if not headings or headings[0]['start'] != 0:
            raise ValueError('source needs an initial heading: ' + rel)
        file_id = 'document:' + rel
        nodes.append({'id': file_id, 'kind': 'document', 'label': path.stem,
                      'path': rel, 'sha256': hashes[rel]})
        stack = []; section_nodes = []
        for index, h in enumerate(headings):
            line = lines[h['start']].rstrip('\r\n')
            match = re.match(r'^(#{1,6})\s+(.+)', line)
            level, title = len(match[1]), match[2]
            while stack and stack[-1]['level'] >= level:
                stack.pop()
            parent = stack[-1]['id'] if stack else file_id
            number = re.match(r'^(\d+(?:\.\d+)+)\b', title)
            number = number[1] if number else (str(int(path.name[:2])) if index == 0 and path.name[:2].isdigit() else None)
            # 标题与祖先路径决定 ID；正文编辑不会引起章节重新编号。
            hierarchy = [s['label'] for s in stack] + [title]
            sid = 'section:' + sha(encoded([rel, hierarchy]))[:20]
            end = headings[index+1]['start'] if index+1 < len(headings) else len(lines)
            subtree_end = next((x['start'] for x in headings[index+1:]
                                if len(re.match(r'^(#+)', lines[x['start']])[1]) <= level), len(lines))
            section = {'id': sid, 'kind': 'section', 'label': title, 'number': number,
                       'path': rel, 'sha256': hashes[rel], 'level': level, 'parent': parent,
                       'hierarchy': hierarchy, 'start': h['start']+1, 'heading_end': h['end'],
                       'end': end, 'subtree_end': subtree_end,
                       'heading_markdown': ''.join(lines[h['start']:h['end']]), 'units': []}
            nodes.append(section); section_nodes.append(section)
            edges.append({'source': parent, 'target': sid, 'relation': 'CONTAINS'})
            stack.append(section)
            body = [b for b in parts if h['end'] <= b['start'] < end]
            for ordinal, group in enumerate(evidence_groups(body, lines), 1):
                a, z = group[0]['start'], group[-1]['end']
                raw = ''.join(lines[a:z])
                uid = sid + ':e' + str(ordinal)
                blocks = [{**b, 'start': b['start']+1,
                           'formula_numbers': re.findall(r'^\((\d+\.\d+[a-z]?)\)\s*$', ''.join(lines[b['start']:b['end']]), re.M)
                           + re.findall(r'\\tag\{([^}]+)\}', ''.join(lines[b['start']:b['end']]))}
                          for b in group]
                unit = {'id': uid, 'kind': 'evidence', 'label': title + f' · {ordinal}',
                        'section': sid, 'path': rel, 'sha256': hashes[rel],
                        'start': a+1, 'end': z, 'markdown': raw, 'content_sha256': sha(raw),
                        'blocks': blocks, 'block_kinds': sorted({b['kind'] for b in group}),
                        'formula_numbers': [n for b in blocks for n in b['formula_numbers']]}
                if len(raw) > 6000:
                    warnings.append({'unit': uid, 'reason': '完整单元超过6000字符；小预算可无法装入', 'characters': len(raw)})
                nodes.append(unit); section['units'].append(uid)
                edges.append({'source': sid, 'target': uid, 'relation': 'HAS_EVIDENCE'})
                for image in re.findall(r'!\[[^\]]*\]\(([^)]+)\)', raw):
                    image_path = (path.parent/image).resolve()
                    if not image_path.is_relative_to(root.resolve()) or not image_path.is_file():
                        raise ValueError('invalid image source: ' + image)
                    image_rel = image_path.relative_to(root.resolve()).as_posix()
                    image_id = 'figure:' + image_rel
                    if not any(n['id'] == image_id for n in nodes):
                        nodes.append({'id': image_id, 'kind': 'figure', 'label': image_rel,
                                      'path': image_rel, 'sha256': hashes[image_rel]})
                    edges.append({'source': uid, 'target': image_id, 'relation': 'ILLUSTRATED_BY'})
        # 分层分块重组必须逐字等于完整 Markdown，空白也不能丢失。
        byid = {n['id']: n for n in nodes}
        reconstructed = ''.join(s['heading_markdown'] + ''.join(byid[u]['markdown'] for u in s['units']) for s in section_nodes)
        if reconstructed != text:
            raise ValueError('source coverage mismatch: ' + rel)
    sections = defaultdict(list); formulas = defaultdict(list)
    for n in nodes:
        if n['kind'] == 'section' and n['number']:
            sections[n['number']].append(n['id'])
        if n['kind'] == 'evidence':
            for number in n['formula_numbers']:
                formulas[number].append(n['id'])
    for n in list(nodes):
        if n['kind'] != 'evidence' or n['path'].startswith('00_'):
            continue
        # 只扫描自然语言块；保留原始偏移，代码/公式/内联字面量不产生边。
        raw = n['markdown']; ls = raw.splitlines(keepends=True)
        masked = list(raw)
        for block in n['blocks']:
            if block['kind'] in {'code', 'formula'}:
                a = sum(map(len, ls[:block['start']-n['start']]))
                z = sum(map(len, ls[:block['end']-n['start']+1]))
                masked[a:z] = ' ' * (z-a)
        scan = ''.join(masked)
        scan = re.sub(r'(`+).*?\1|\$[^$\n]*\$', lambda m: ' '*len(m[0]), scan)
        number = r'\d+(?:\.\d+)*(?:[a-z])?'
        numbers = rf'\(?{number}\)?(?:\s*(?:,\s*(?:and\s+)?|and\s+|&\s*)\(?{number}\)?)*'
        equation_numbers = numbers.replace(number, r'\d+\.\d+[a-z]?')
        seen_refs = set()
        for pattern, lookup, relation in [
            (rf'\b(?:sections?|secs?\.?|chapters?)\s+({numbers})(?!\w|\.\d)', sections, 'REFERS_TO_SECTION'),
            (rf'\b(?:equations?|eqs?\.?)\s+({equation_numbers})(?!\w|\.\d)', formulas, 'REFERS_TO_FORMULA'),
            (r'\bsee\s+(\d+\.\d+(?:\.\d+)*)(?!\w|\.\d)', sections, 'REFERS_TO_SECTION')]:
            for m in re.finditer(pattern, scan, re.I):
                quote = raw[m.start():m.end()]
                for ref in re.findall(number, m[1]):
                    targets = sorted(set(lookup[ref]))
                    if len(targets) == 1 and targets[0] != n['id']:
                        key = (targets[0], relation)
                        if key not in seen_refs:
                            edges.append({'source': n['id'], 'target': targets[0], 'relation': relation,
                                          'quote': quote, 'evidence': [n['id']],
                                          'line_start': n['start']+raw[:m.start()].count('\n')})
                            seen_refs.add(key)
                    elif len(targets) != 1:
                        warnings.append({'unit': n['id'], 'reason': '未解析或歧义的明示引用', 'quote': quote, 'reference': ref})
    graph = {'schema': SCHEMA, 'inventory': hashes, 'nodes': nodes, 'edges': edges,
             'warnings': warnings, 'builder_sha256': sha(Path(__file__).read_bytes()),
             'limits': ['Markdown原文保真不等于物理内容已审核', '父章节上下文不自动成为所有子模型的约束']}
    graph['snapshot'] = sha(encoded(graph))
    validate(graph, root)
    return graph


def validate(graph, root):
    if inventory(Path(root)) != graph['inventory']:
        raise ValueError('manual sources changed; rebuild required')
    byid = {n['id']: n for n in graph['nodes']}
    if len(byid) != len(graph['nodes']):
        raise ValueError('duplicate graph identity')
    for e in graph['edges']:
        if e['source'] not in byid or e['target'] not in byid:
            raise ValueError('dangling graph edge')
    expected = sha(encoded({k: v for k, v in graph.items() if k != 'snapshot'}))
    if graph['snapshot'] != expected:
        raise ValueError('graph snapshot mismatch')
    for n in graph['nodes']:
        if n['kind'] != 'evidence':
            continue
        lines = (Path(root)/n['path']).read_bytes().decode().splitlines(keepends=True)
        if ''.join(lines[n['start']-1:n['end']]) != n['markdown'] or sha(n['markdown']) != n['content_sha256']:
            raise ValueError('evidence differs from original source')
        for b in n['blocks']:
            if not n['start'] <= b['start'] <= b['end'] <= n['end']:
                raise ValueError('block crosses evidence boundary')
    return {'status': 'pass', 'snapshot': graph['snapshot'],
            'counts': dict(Counter(n['kind'] for n in graph['nodes'])), 'edges': len(graph['edges']),
            'blocks': dict(Counter(b['kind'] for n in graph['nodes'] if n['kind'] == 'evidence' for b in n['blocks'])),
            'formula_numbers': sum(len(n.get('formula_numbers', [])) for n in graph['nodes']),
            'warnings': graph['warnings']}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=['build', 'check'])
    p.add_argument('--source', type=Path, default=ROOT/'corpus/manual/markdown')
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    if args.command == 'build':
        graph = build(args.source); write(args.output, graph)
    else:
        graph = json.loads(args.output.read_text(encoding="utf-8"))
    print(encoded(validate(graph, args.source)))


if __name__ == '__main__':
    main()
