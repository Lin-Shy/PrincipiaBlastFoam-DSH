"""Natural scope with phase identity and a bounded factory evidence entry point."""
import json,os
from mcp_servers.principia_retrieval import knowledge_navigation,server
from experiments.retrieval_method.native_natural_server import locate as natural_locate
from experiments.retrieval_method.case_identity import phase_identity,attach_identity
from experiments.retrieval_method.factory_route import FactoryRoute

_original_source=knowledge_navigation.source


def route():return FactoryRoute(os.environ['PRINCIPIA_FACTORY_GRAPH'])


def locate(query,tutorial_case,translation='',budget=5000):
    packet=natural_locate(query,tutorial_case,translation,budget)
    identity=phase_identity(knowledge_navigation.navigator().engine,packet)
    if identity:
        graph=route()
        ref=graph.reference(knowledge_navigation.navigator().engine,packet,identity)
        if ref:
            identity['factory_route']=ref['source']
            fact=graph.inline_evidence(include_transport=ref['basic_phase_flow'])
            if fact:identity['factory_evidence']=fact
    result=attach_identity(packet,identity,budget)
    if identity and 'case_identity' not in result and 'factory_route' in identity:
        identity.pop('factory_evidence',None);result=attach_identity(packet,identity,budget)
        if 'case_identity' not in result:
            identity.pop('factory_route');result=attach_identity(packet,identity,budget)
    return result


def source(path,start=1,end=80,budget=5000):
    if not path.startswith('factory_route/'):return _original_source(path,start,end,budget)
    if type(start)!=int or type(end)!=int or not 1<=start<=end or end-start>=1000:raise ValueError('invalid source range')
    if type(budget)!=int or not 1000<=budget<=24000:raise ValueError('invalid budget')
    graph=route();relative=path.removeprefix('factory_route/')
    if relative.startswith('path/'):
        parts=relative.split('/')
        if len(parts)!=3:raise ValueError('invalid factory path')
        text=graph.path_source(parts[1],parts[2])
    else:
        text=(graph.guide() if relative=='guide' else
          graph.node_source(relative.removeprefix('node/')) if relative.startswith('node/') else graph.read(relative))
    lines=text.splitlines(keepends=True)
    if start>len(lines):raise ValueError('start exceeds source length')
    end=min(end,len(lines));result={'path':path,'start':start,'end':end,'snapshot':graph.graph['snapshot'],'text':''.join(lines[start-1:end]),'complete':True}
    while len(json.dumps(result,ensure_ascii=False,separators=(',',':')))>budget:
        result['text']=result['text'][:-100];result['complete']=False
        if not result['text']:return {'status':'insufficient_budget'}
    return result


def main():
    knowledge_navigation.locate=locate;knowledge_navigation.source=source
    server.main()


if __name__=='__main__':main()
