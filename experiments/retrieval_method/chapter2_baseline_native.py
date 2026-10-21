"""独立对照的原生排名导出；此模块不进入自研图检索进程。"""
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re
import time

from candidate_graph_utils import tokens


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def query_text(question, plan):
    return "\n".join([question, plan.get("translation", ""), *plan.get("needs", [])])


class OriginalSources:
    def __init__(self, corpus, manifest):
        self.corpus = Path(corpus).resolve()
        self.hashes = json.loads(Path(manifest).read_text(encoding="utf-8"))["files"]

    def read(self, path, cache):
        if path not in self.hashes:
            return None
        if path not in cache:
            file = (self.corpus/path).resolve()
            if not file.is_relative_to(self.corpus):
                raise ValueError("source outside authoritative corpus")
            raw = file.read_bytes()
            if digest(raw) != self.hashes[path]:
                raise ValueError("authoritative source drift")
            try:
                text = raw.decode()
                cache[path] = None if "\x00" in text else text.splitlines()
            except UnicodeDecodeError:
                cache[path] = None
        return cache[path]

    def map(self, native, cache=None):
        cache = {} if cache is None else cache
        items = []
        for row in native:
            path = row.get("path", "")
            lines = self.read(path, cache)
            start, end = row.get("start"), row.get("end")
            image = Path(path).suffix.casefold() in {".png", ".jpg", ".jpeg", ".gif", ".eps", ".svg", ".pdf", ".webp"}
            if image or lines is None or type(start) is not int or type(end) is not int or not 1 <= start <= end <= len(lines):
                items.append({**row, "mapping_status": "unmappable", "ranges": [],
                              "source_sha256": self.hashes.get(path), "reason": "binary/nonmanifest/missing-or-invalid-line-location"})
                continue
            items.append({**row, "mapping_status": "mapped", "source_sha256": self.hashes[path],
                          "source_kind": "manual" if path.startswith("manual/") else "tutorial",
                          "scope": {"case_directory": "/".join(path.split("/")[:3]) if path.startswith("tutorials/") else None},
                          "ranges": [{"start": start, "end": end, "lines": lines[start-1:end]}]})
        return {"schema": "native-ranking-with-authoritative-source-ranges-v1", "items": items}


class NoGraphBM25:
    """只在一次查询内对原文分段计算BM25；不读图或E5索引。"""
    def __init__(self, corpus, manifest):
        self.sources = OriginalSources(corpus, manifest)

    def query(self, question, plan, limit=64):
        started = time.monotonic()
        query = Counter(tokens(query_text(question, plan)))
        cache, docs = {}, []
        for path in sorted(self.sources.hashes):
            lines = self.sources.read(path, cache)
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
                text = "\n".join(lines[start-1:end])
                counts = Counter(tokens(path+"\n"+text))
                docs.append({"path": path, "start": start, "end": end, "counts": counts,
                             "length": sum(counts.values()), "native_unit": digest(f"{path}:{start}:{end}".encode())[:24]})
                first = end+1
        df = Counter(t for doc in docs for t in doc["counts"] if t in query)
        average = sum(d["length"] for d in docs)/max(1,len(docs))
        ranked = []
        for doc in docs:
            score = 0.0
            for term, qf in query.items():
                tf = doc["counts"].get(term,0)
                if tf:
                    idf = math.log(1+(len(docs)-df[term]+.5)/(df[term]+.5))
                    denominator = tf+1.2*(1-.75+.75*doc["length"]/max(1,average))
                    score += idf*tf*2.2/denominator*min(qf,2)
            if score:
                ranked.append({k:v for k,v in doc.items() if k not in {"counts","length"}} | {"score":score})
        ranked.sort(key=lambda r:(-r["score"],r["native_unit"]))
        native=[{**row,"native_rank":i} for i,row in enumerate(ranked[:limit],1)]
        packet=self.sources.map(native,cache)
        return packet,{"seconds":time.monotonic()-started,"passages_scanned":len(docs),"graph_loaded":False,
                       "external_index_loaded":False,"mode":"query-local-raw-BM25","rank_is_before_character_budget":True}


class DenseE5:
    """独立冻结E5向量对照；不加载BM25统计、图或查询embedding缓存。"""
    def __init__(self, corpus, manifest, index):
        import numpy as np
        from candidate_hybrid import model_load
        self.sources=OriginalSources(corpus,manifest)
        index=Path(index)
        self.manifest=json.loads((index/"manifest.json").read_text(encoding="utf-8"))
        for name,expected in self.manifest["files"].items():
            if digest((index/name).read_bytes())!=expected:
                raise ValueError("frozen E5 index drift")
        self.docs=json.loads((index/"passages.json").read_text(encoding="utf-8"))
        if any(self.sources.hashes.get(d["path"])!=d["source_sha256"] for d in self.docs):
            raise ValueError("E5 passages outside authoritative corpus")
        self.vectors=np.load(index/"embeddings.npy",allow_pickle=False)
        self.model=model_load(self.manifest["model"])

    def query(self,question,plan,limit=64):
        started=time.monotonic()
        vector=self.model.encode(["query: "+query_text(question,plan)],normalize_embeddings=True,convert_to_numpy=True)[0]
        scores=self.vectors@vector
        order=sorted(range(len(self.docs)),key=lambda i:(-float(scores[i]),self.docs[i]["id"]))[:limit]
        native=[{"native_unit":self.docs[i]["id"],"native_rank":rank,"score":float(scores[i]),
                 "path":self.docs[i]["path"],"start":self.docs[i]["start"],"end":self.docs[i]["end"]} for rank,i in enumerate(order,1)]
        return self.sources.map(native),{"seconds":time.monotonic()-started,"dense_dot_products":len(self.docs),
            "query_embeddings_computed":1,"query_embedding_cache":False,"mode":"dense-E5-only","graph_loaded":False,
            "external_index_loaded":True,"rank_is_before_character_budget":True}


class GraphifyNative:
    """固定上游BFS/种子算法，仅捕获原生渲染顺序后映射原文。"""
    def __init__(self, corpus, manifest, graph, path_map=None):
        import graphify.serve as serve
        self.serve=serve
        self.sources=OriginalSources(corpus,manifest)
        self.graph=serve._load_graph(str(graph))
        if self.graph.graph.get("_learning_overlay"):
            raise ValueError("unfrozen Graphify learning overlay present")
        mapping=json.loads(Path(path_map).read_text()) if path_map else {}
        # 既有path-map.json已经是native/adapted路径→权威原路径。
        self.inverse=mapping

    def query(self,question,plan,limit=64):
        started=time.monotonic()
        captured=[]
        original=self.serve._subgraph_to_text
        def observe(graph,nodes,edges,token_budget=2000,*,seeds=None):
            seeds=seeds or []
            hits=[n for n in seeds if n in nodes]
            distances={n:0 for n in hits}
            frontier,hop=hits,0
            while frontier:
                hop+=1
                following=[]
                for node in frontier:
                    neighbors=list(graph.successors(node))+list(graph.predecessors(node)) if graph.is_directed() else graph.neighbors(node)
                    for neighbor in neighbors:
                        if neighbor in nodes and neighbor not in distances:
                            distances[neighbor]=hop
                            following.append(neighbor)
                frontier=following
            order=hits+sorted(nodes-set(seeds),key=lambda n:(distances.get(n,1<<30),-graph.degree(n),str(n)))
            captured.extend((identity,dict(graph.nodes[identity])) for identity in order)
            # 与上游同一排序，给足预算避免任何原生字符截断。
            raw=original(graph,nodes,edges,10**9,seeds=seeds)
            if len([line for line in raw.splitlines() if line.startswith("NODE ")])!=len(order):
                raise ValueError("Graphify captured ordering/renderer drift")
            return raw
        self.serve._subgraph_to_text=observe
        try:
            raw=self.serve._query_graph_text(self.graph,query_text(question,plan),mode="bfs",depth=2,token_budget=10**9)
        finally:
            self.serve._subgraph_to_text=original
        native=[]
        cache={}
        for rank,(identity,data) in enumerate(captured[:limit],1):
            source=str(data.get("source_file") or "")
            path=self.inverse.get(source,source)
            loc=str(data.get("source_location") or "")
            match=re.fullmatch(r"L(\d+)(?:-L?(\d+))?",loc)
            start,end=(int(match[1]),int(match[2] or match[1])) if match else (None,None)
            lines=self.sources.read(path,cache)
            if lines and match:
                if data.get("metadata",{}).get("kind")=="file":
                    start,end=1,len(lines)
                elif start==end:
                    start,end=max(1,start-8),min(len(lines),end+8)
            elif lines:
                # 上游文档常给标题或留空；先按原文唯一标题找所属节。
                headings=[]
                fence=None
                for number,line in enumerate(lines,1):
                    marker=re.match(r"^\s*(`{3,}|~{3,})",line)
                    if marker:
                        fence=None if fence==marker[1][0] else marker[1][0] if fence is None else fence
                        continue
                    heading=re.match(r"^(#{1,6})\s+(.+?)\s*$",line) if fence is None else None
                    if heading:
                        headings.append((number,len(heading[1]),heading[2]))
                normalize=lambda value:re.sub(r"^\d+(?:\.\d+)*\s+","",value).strip().casefold()
                hits=[(number,level) for number,level,title in headings if loc.strip() and normalize(title)==normalize(loc)]
                if len(hits)==1:
                    start,level=hits[0]
                    end=next((number-1 for number,depth,title in headings if number>start and depth<=level),len(lines))
                else:
                    # 原生节点只能定位文件时回读整个权威文件，记录弱定位，
                    # 仍受排名前缀和相同字符预算约束，不补写精确位置。
                    start,end=1,len(lines)
            native.append({"native_unit":str(identity),"native_rank":rank,"path":path,"start":start,"end":end,
                           "native_source_file":source,"native_source_location":loc,
                           "mapping_basis":"declared-lines" if match else "unique-source-heading-or-whole-file-fallback"})
        return self.sources.map(native,cache),{"seconds":time.monotonic()-started,"upstream_ranked_nodes":len(captured),
            "native_exported_nodes":len(native),"upstream_navigation_characters":len(raw),"graph_loaded":True,
            "mode":"original-Graphify-BFS-depth2-render-order","rank_is_before_character_budget":True,
            "mapping_policy":"AST files whole; declared ranges exact; point +/-8; unique literal title owned section; otherwise known text file whole with weak-location flag; images/binary/nonmanifest retained as unmappable"}
