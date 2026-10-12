"""Experimental exact-combination projection, retaining the complete edit bundle."""
import copy
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import re
from mcp_servers.principia_retrieval import knowledge_navigation,server
from experiments.retrieval_method import native_factory_server as factory
from experiments.retrieval_method.combination_graph import CombinationGraph


@lru_cache(maxsize=2)
def combinations(path):return CombinationGraph(path)


def proposed_components(engine,packet):
    """Bind the edited phase to an exact basic phase tuple from pinned state."""
    edits=packet.get('model_draft',{}).get('edits',[])
    selectors=[e for e in edits if e['path']=='constant/phaseProperties' and re.fullmatch(r'\w+/thermoType/(?:transport|thermo|equationOfState)',e['entry'])]
    if len(selectors)!=1 or 'factory_route' not in packet.get('case_identity',{}):return None
    phase=selectors[0]['entry'].split('/')[0]
    if phase not in packet['case_identity']['phases']:return None
    relative=packet['case']+'/constant/phaseProperties';root=(engine.skill/'corpus').resolve();path=(root/relative).resolve()
    if not path.is_relative_to(root):raise ValueError('case path escapes corpus')
    raw=path.read_bytes();sha=hashlib.sha256(raw).hexdigest()
    if sha!=engine.graph['inventory'].get(relative):raise ValueError('combination case source changed')
    import knowledge as k
    entries,diagnostics=k.parse_dictionary(raw.decode())
    if diagnostics or any(not e['resolved'] or '@' in e['dictionary_path'] for e in entries):return None
    values={e['dictionary_path']:e['value'] for e in entries}
    if values.get(phase+'/type')!='basic' or values.get(phase+'/state','phaseFluid')!='phaseFluid':return None
    for e in edits:
        if e['path']=='constant/phaseProperties':
            if e['value'] is None:values.pop(e['entry'],None)
            else:values[e['entry']]=e['value']
    components={'base':'phaseFluid','type':values.get(phase+'/type'),'specie':'specie'}
    for key in ('transport','thermo','equationOfState'):
        value=values.get(phase+'/thermoType/'+key)
        if not isinstance(value,str) or not re.fullmatch(r'\w+',value):return None
        components[key]=value
    return {'phase':phase,'components':components,'source_sha256':sha,
            'state_scope':'固定教程加拟议编辑的组合；修改后须依据实际副本重新核对。'}


def attach(packet,binding,graph,budget):
    result=copy.deepcopy(packet)
    if binding:
        result['model_combination']={**binding,**graph.summary(binding['components'])}
    wire=lambda:len(json.dumps(result,ensure_ascii=False,separators=(',',':')))
    # Preserve relation IDs, complete operations, conditions, defaults and scope.
    # Only duplicate excerpt text is shortened after resolving all evidence.
    while wire()>budget:
        excerpts=[x for x in result.get('locations',[]) if x.get('text')]
        if not excerpts:return {'status':'insufficient_budget','locations':[],
                               'limits':'完整修改、条件及组合来源超过预算；未返回残缺草案。'}
        item=max(excerpts,key=lambda x:len(x['text']))
        item['text']=item['text'][:-min(len(item['text']),wire()-budget+10)];item['complete']=False
    return result


def locate(query,tutorial_case,translation='',budget=5000):
    if type(budget)!=int or not 1000<=budget<=24000:raise ValueError('budget must be 1000..24000')
    packet=factory.locate(query,tutorial_case,translation,24000)
    binding=proposed_components(knowledge_navigation.navigator().engine,packet)
    graph=combinations(os.environ['PRINCIPIA_COMBINATION_GRAPH'])
    if not graph.compatible_corpus(knowledge_navigation.navigator().engine.graph['inventory']):
        return {'status':'combination_source_version_mismatch','locations':[],
                'limits':'组合注册源码与当前语料版本无法核对；未返回跨版本草案。'}
    return attach(packet,binding,graph,budget)


def source(path,start=1,end=80,budget=5000):
    if not path.startswith('combination_sources/'):return factory.source(path,start,end,budget)
    if type(start)!=int or type(end)!=int or not 1<=start<=end or end-start>=1000:raise ValueError('invalid source range')
    if type(budget)!=int or not 1000<=budget<=24000:raise ValueError('invalid budget')
    graph=combinations(os.environ['PRINCIPIA_COMBINATION_GRAPH'])
    text=json.dumps(graph.source(path.removeprefix('combination_sources/')),ensure_ascii=False,indent=2)
    lines=text.splitlines(keepends=True)
    if start>len(lines):raise ValueError('source range beyond evidence')
    result={'path':path,'start':start,'end':min(end,len(lines)),'text':''.join(lines[start-1:end]),'snapshot':graph.graph['snapshot'],'complete':end>=len(lines)}
    wire=lambda:len(json.dumps(result,ensure_ascii=False,separators=(',',':')))
    while wire()>budget:
        result['text']=result['text'][:-max(1,wire()-budget+10)];result['complete']=False
        if not result['text'] and wire()>budget:return {'status':'insufficient_budget'}
    return result


def main():
    knowledge_navigation.locate=locate;knowledge_navigation.source=source;server.main()


if __name__=='__main__':main()
