"""指导书参数表的确定性结构层：保留模型章节、原始行及默认/条件作用域。"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re

import manual_graph

SCHEMA = "manual-parameters-v1"


def sha(value):
    return hashlib.sha256(value if isinstance(value,bytes) else value.encode()).hexdigest()


def cells(line):
    return [part.strip() for part in re.split(r"(?<!\\)\|",line.strip().strip("|"))]


def identifiers(label):
    """只作标记级抽取；公式符号的拼写候选不提升为已核验配置键。"""
    names=[]
    for code in re.findall(r"`([^`]+)`",label):
        if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*",code):
            names.append({"name":code,"status":"explicit_code_label"})
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*",label):
        names.append({"name":label,"status":"literal_table_label"})
    for formula in re.findall(r"\$([^$]+)\$",label):
        if re.fullmatch(r"[A-Za-z](?:_[A-Za-z0-9]+|_\{[A-Za-z0-9]+\})?",formula):
            name=re.sub(r"[_{}]","",formula)
            names.append({"name":name,"status":"notation_normalization_candidate"})
    return sorted({(n["name"],n["status"]):n for n in names}.values(),key=lambda n:(n["name"],n["status"]))


def qualifiers(description):
    # Store complete default clauses, including 'for gas', 'only for solid', etc.
    # This is not a solver default resolver and does not invent omitted defaults.
    defaults=[m.group(1).strip() for m in re.finditer(r"\(([^()]*(?i:default)[^()]*)\)",description)]
    if re.search(r"\bdefault\b",description,re.I) and not defaults:
        defaults=[description]
    conditional=bool(re.search(r"\b(if|when|unless|only|for gas|for solid)\b",description,re.I))
    requirements=[description] if re.search(r"\b(required|optional|must|needs? to|only|unless|if|when)\b",description,re.I) else []
    return {"default_statements":defaults,"default_scope":"this row and its owning section only",
            "default_status":"manual_explicit_clause" if defaults else "not_stated_in_this_row",
            "conditional_text":description if conditional else None,"requirement_statements":requirements,
            "unit_literals":re.findall(r"\[([^\[\]]*)\]",description)}


def build(manual):
    nodes,edges,issues=[],[],[]
    byid={n["id"]:n for n in manual["nodes"]}
    counts=Counter()
    for unit in manual["nodes"]:
        if unit["kind"]!="evidence":
            continue
        section=byid[unit["section"]]
        lines=unit["markdown"].splitlines()
        for block in unit["blocks"]:
            if block["kind"]!="table":
                continue
            rows=[(n,lines[n-unit["start"]]) for n in range(block["start"],block["end"]+1)
                  if lines[n-unit["start"]].strip().startswith("|")]
            if len(rows)<3:
                continue
            header=cells(rows[0][1]); first=header[0].strip("` ").casefold()
            if first not in {"variable","entry","parameter","keyword","option"}:
                continue
            separators=cells(rows[1][1])
            if len(separators)!=len(header) or not all(re.fullmatch(r":?-{3,}:?",s) for s in separators):
                issues.append({"unit":unit["id"],"line":rows[1][0],"reason":"parameter_table_separator_invalid"})
                continue
            descriptions=[i for i,name in enumerate(header) if name.casefold()=="description"]
            if len(descriptions)!=1:
                issues.append({"unit":unit["id"],"line":rows[0][0],"reason":"parameter_table_description_column_ambiguous"})
                continue
            desc_index=descriptions[0]
            counts["recognized_tables"]+=1
            for line,raw in rows[2:]:
                row=cells(raw)
                if len(row)!=len(header):
                    issues.append({"unit":unit["id"],"line":line,"reason":"table_row_column_mismatch","raw":raw})
                    continue
                label,description=row[0],row[desc_index]
                if not label or not description:
                    continue
                identity=[SCHEMA,section["id"],unit["path"],line,label]
                uid="manual_parameter:"+sha(json.dumps(identity,ensure_ascii=False,separators=(",",":")))[:24]
                evidence={"path":"manual/markdown/"+unit["path"],"sha256":unit["sha256"],
                          "line_start":line,"line_end":line,"table_header_line":rows[0][0],
                          "section":section["label"],"section_id":section["id"],"pdf_page":None}
                node={"id":uid,"kind":"manual_parameter","label":label,"description":description,
                      "identifiers":identifiers(label),"raw_row":raw,"columns":dict(zip(header,row)),
                      "section":section["id"],"hierarchy":section["hierarchy"],"evidence_unit":unit["id"],
                      "evidence":evidence,"data_version":unit["sha256"],"source_category":"manual",
                      "extraction_method":"markdown_parameter_table_row","evidence_status":"manual_explicit",
                      "confidence":1.0,"confidence_scope":"row transcription and ownership only, not physical correctness or key alignment",
                      **qualifiers(description)}
                for column,value in node['columns'].items():
                    name=column.strip().casefold()
                    if name in {'default','default value'} and value.strip().casefold() not in {'','-','—','n/a','not specified'}:
                        node['default_statements'].append(column+': '+value)
                        node['default_status']='manual_explicit_clause'
                    if name in {'required','optional','condition'} and value.strip():
                        node['requirement_statements'].append(column+': '+value)
                nodes.append(node)
                edges.extend([
                    {"source":section["id"],"target":uid,"relation":"HAS_PARAMETER_ROW","evidence":[evidence],"status":"manual_explicit"},
                    {"source":uid,"target":unit["id"],"relation":"DOCUMENTED_IN_EVIDENCE","evidence":[evidence],"status":"original_table_context"}])
                counts["parameters"]+=1
                counts["rows_with_explicit_default"]+=bool(node["default_statements"])
                counts["conditional_rows"]+=bool(node["conditional_text"])
                counts["rows_with_identifier_candidates"]+=bool(node["identifiers"])
    graph={"schema":SCHEMA,"parent_snapshot":manual["snapshot"],"source_inventory":manual["inventory"],
           "builder_sha256":sha(Path(__file__).read_bytes()),"nodes":nodes,"edges":edges,"issues":issues,"counts":dict(counts),
           "llm_calls":0,"llm_tokens":0,
           "limits":["章节包含关系不把父章节默认或条件无条件传播给子模型。",
                     "未写默认的参数行不证明整个指导书或求解器没有默认。",
                     "公式符号与字典键之间只有拼写候选，尚未跨来源核验。",
                     "实例值不参与手册参数或默认提取；本构建器不读取教程或题集。"]}
    graph["snapshot"]=sha(json.dumps(graph,ensure_ascii=False,sort_keys=True,separators=(",",":")))
    return graph


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    if a.output.exists():
        raise ValueError("use a new output to preserve the previous graph")
    manual=manual_graph.build(a.source)
    graph=build(manual)
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(graph,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({"snapshot":graph["snapshot"],"counts":graph["counts"],"issues":graph["issues"]},ensure_ascii=False))


if __name__=="__main__":main()
