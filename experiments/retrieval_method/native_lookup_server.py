"""Experimental edit projection with traversable, source-bound lookup semantics."""
import json
import os
from mcp_servers.principia_retrieval import knowledge_navigation,server
from experiments.retrieval_method.native_draft_server import locate_drafts
from experiments.retrieval_method.lookup_semantics import LookupSemantics

_original_source=knowledge_navigation.source


def graph():
    return LookupSemantics(os.environ['PRINCIPIA_LOOKUP_GRAPH'])


def locate(query,tutorial_case,translation='',budget=5000):
    packet=locate_drafts(query,tutorial_case,translation,budget)
    reference=graph().reference(packet)
    if reference:
        result={**packet,'lookup_semantics':reference}
        if len(json.dumps(result,ensure_ascii=False,separators=(',',':')))<=budget:return result
    return packet


def source(path,start=1,end=80,budget=5000):
    if not path.startswith('lookup_semantics/'):return _original_source(path,start,end,budget)
    if type(start)!=int or type(end)!=int or not 1<=start<=end or end-start>=1000:raise ValueError('invalid source range')
    if type(budget)!=int or not 1000<=budget<=24000:raise ValueError('invalid budget')
    g=graph();relative=path.removeprefix('lookup_semantics/')
    text=g.rule_text() if relative=='rule' else g.read_file(relative)
    lines=text.splitlines(keepends=True)
    if start>len(lines):raise ValueError('start exceeds source length')
    end=min(end,len(lines));raw=''.join(lines[start-1:end])
    result={'path':path,'start':start,'end':end,'snapshot':g.graph['snapshot'],'text':raw,'complete':True}
    while len(json.dumps(result,ensure_ascii=False,separators=(',',':')))>budget:
        result['text']=result['text'][:-100];result['complete']=False
        if not result['text']:return {'status':'insufficient_budget'}
    return result


def main():
    knowledge_navigation.locate=locate
    knowledge_navigation.source=source
    server.main()


if __name__=='__main__':main()
