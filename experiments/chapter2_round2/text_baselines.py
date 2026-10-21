"""无图文本对照。公用分段逐字复现历史 NoGraphBM25；只依赖原文。"""
from collections import Counter
import hashlib
import math
import re
import time

from common import RESOURCES, read, sha
from chapter2_baseline_native import OriginalSources
from candidate_graph_utils import tokens

def make_passages(sources):
    docs = []
    for path in sorted(sources.hashes):
        lines = sources.read(path, {})
        if not lines:
            continue
        first = 1
        while first <= len(lines):
            end, size = first-1, 0
            while end < len(lines):
                if size+len(lines[end])+1 > 1500 and end >= first:
                    break
                size += len(lines[end])+1
                end += 1
            start = max(1, first-4)
            docs.append(dict(path=path, start=start, end=end, text='\n'.join(lines[start-1:end]),
                             source_sha256=sources.hashes[path],
                             id=hashlib.sha256(f'{path}:{start}:{end}'.encode()).hexdigest()[:24]))
            first = end+1
    return docs

class BM25:
    def __init__(self, corpus=RESOURCES/'corpus', manifest=RESOURCES/'source-map.json'):
        start = time.monotonic()
        self.sources = OriginalSources(corpus, manifest)
        self.docs = make_passages(self.sources)
        self.counts = [Counter(tokens(d['path']+'\n'+d['text'])) for d in self.docs]
        self.lengths = [sum(c.values()) for c in self.counts]
        self.df = Counter(t for count in self.counts for t in count)
        self.average = sum(self.lengths)/max(1,len(self.docs))
        self.load_seconds = time.monotonic()-start

    def rank(self, query, limit=64):
        qt = Counter(tokens(query+'\n')); ranked = []
        for i, count in enumerate(self.counts):
            value = 0.
            for term, qf in qt.items():
                tf = count.get(term, 0)
                if tf:
                    idf = math.log(1+(len(self.docs)-self.df[term]+.5)/(self.df[term]+.5))
                    value += idf*tf*2.2/(tf+1.2*(1-.75+.75*self.lengths[i]/max(1,self.average)))*min(qf,2)
            if value:
                d = self.docs[i]
                ranked.append(dict(path=d['path'], start=d['start'], end=d['end'], score=value, native_unit=d['id']))
        ranked.sort(key=lambda r:(-r['score'],r['native_unit']))
        return [dict(r,native_rank=i) for i,r in enumerate(ranked[:limit],1)]

def hierarchy_ranges(lines):
    """独立解析 Markdown 标题和字典花括号；无图类型、别名或成员输入。"""
    parents = []; headings = []; fence = None
    for number,line in enumerate(lines,1):
        mark = re.match(r'^\s*(`{3,}|~{3,})',line)
        if mark:
            fence = None if fence == mark[1][0] else (mark[1][0] if fence is None else fence)
            continue
        match = re.match(r'^(#{1,6})\s+',line) if fence is None else None
        if match:
            headings.append((number,len(match[1])))
    for start,level in headings:
        end = next((n-1 for n,l in headings if n>start and l<=level),len(lines))
        parents.append((start,end,'markdown_section'))
    text = '\n'.join(lines)
    masked = re.sub(r'/\*.*?\*/|//[^\n]*|"(?:\\.|[^"\\])*"',
                    lambda m:re.sub(r'[^\n]',' ',m[0]),text,flags=re.S)
    stack = []; line = 1
    for char in masked:
        if char == '\n':line += 1
        elif char == '{':stack.append(line)
        elif char == '}' and stack:
            start = stack.pop()
            if not lines[start-1].strip().strip('{'):
                start = max(1,start-1)
            parents.append((start,line,'dictionary_braces'))
    return sorted(set(parents),key=lambda p:(p[1]-p[0],p[0],p[2]))

class ParentBM25:
    def __init__(self, bm25):
        self.bm25 = bm25
        self.load_seconds = 0.

    def rank(self, query, limit=64):
        anchors = self.bm25.rank(query,limit); result = []
        for row in anchors:
            result.append({**row,'delivery_role':'anchor'})
            if row['native_rank'] > 10:
                continue
            lines = self.bm25.sources.read(row['path'],{})
            parents = [p for p in hierarchy_ranges(lines) if p[0]<=row['start']<=row['end']<=p[1]]
            selected = next((p for p in parents if len('\n'.join(lines[p[0]-1:p[1]]))<=1200),None)
            # Graph fragments are not public parser units: freeze independent
            # nearest enclosing parent, else nearest complete adjacent lines.
            left,right = (selected[0],selected[1]) if selected else (row['start'],row['end'])
            extra = 0
            if selected is None:
                while True:
                    changed = False
                    for side in ['left','right']:
                        candidate = left-1 if side=='left' else right+1
                        if not 1<=candidate<=len(lines):continue
                        cost = len(lines[candidate-1])+1
                        if extra+cost>1200:continue
                        extra += cost;changed = True
                        if side=='left':left=candidate
                        else:right=candidate
                    if not changed:break
            for a,b in [(left,row['start']-1),(row['end']+1,right)]:
                if a<=b:
                    result.append(dict(row,start=a,end=b,delivery_role='context',
                        parent_parser=selected[2] if selected else 'adjacent_lines',
                        added_characters=len('\n'.join(lines[a-1:b]))))
        return result

class RRF:
    def __init__(self, left, right):
        self.left,self.right=left,right
        self.load_seconds=0.
        self.last_trace={}

    def rank(self, query, limit=64):
        left=self.left.rank(query,64);right=self.right.rank(query,64)
        values={}
        for rows in [left,right]:
            seen=set()
            for rank,row in enumerate(rows,1):
                key=(row['path'],row['start'],row['end'])
                if key not in seen:values[key]=values.get(key,0)+1/(60+rank)
                seen.add(key)
        order=sorted(values,key=lambda k:(-values[k],k))[:limit]
        result=[dict(path=p,start=a,end=b,score=values[(p,a,b)],native_rank=i)
                for i,(p,a,b) in enumerate(order,1)]
        self.last_trace=dict(left=left,right=right,fusion=result,k=60,pool=64)
        return result
