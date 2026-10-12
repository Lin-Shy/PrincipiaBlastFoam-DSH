"""零API汇总闭合规划/原生检索/回答耗时；区分会话阶段和分段相加估计。"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics
import sys


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path):
    return json.loads(path.read_text())


def stats(values):
    values=sorted(values)
    return {'n':len(values),'mean_seconds':statistics.mean(values),
            'median_seconds':statistics.median(values),'p95_seconds':values[math.ceil(.95*len(values))-1]}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('root','output'):
        parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args()
    root=args.root.resolve()
    sys.path.insert(0,str(root/'runtime'))
    from chapter2_formal_runtime import verify
    protocol,protocol_sha=verify(root,require_snapshot=False)
    bindings,plan_times,unknown={}, {}, {}
    for path in sorted((root/'planner').glob('*/compiled.json')):
        value=load(path);request=path.parent/'plan.json'
        if value['protocol_sha256']!=protocol_sha or value['response_sha256']!=sha(request):
            raise ValueError('规划身份漂移')
        record=load(request)
        if record['status']!='response':raise ValueError('规划未收到响应')
        plan_times[path.parent.name]=sum(e['seconds'] for e in record['events'] if isinstance(e.get('seconds'), (int,float)))
        unknown[path.parent.name]=sum(not isinstance(e.get('seconds'), (int,float)) for e in record['events'])
        bindings[str(path.relative_to(root))]=sha(path)
        bindings[str(request.relative_to(root))]=sha(request)
    if len(plan_times)!=288:raise ValueError('需要全部288共享规划')
    summaries,rows={},[]
    arms=['full','no_cross','no_graph','graphify_native','graphify_text_adapter','e5']
    for arm in arms:
        paths=sorted((root/'answers'/arm).glob('*/compiled.json'))
        if {p.parent.name for p in paths}!=set(plan_times):raise ValueError('需要每臂全部288会话')
        values={'answer_stage':[],'native_query':[],'observed_serial_component_sum':[]}
        unknown_sessions=0
        for path in paths:
            key=path.parent.name
            native_path=root/'native'/arm/(key+'.json')
            answer,native=load(path),load(native_path)
            if (answer['protocol_sha256']!=protocol_sha or native['protocol_sha256']!=protocol_sha or
                answer['native_response_sha256']!=sha(native_path) or
                native['planner_compiled_sha256']!=sha(root/'planner'/key/'compiled.json') or
                answer['question']!=native['question'] or answer['repeat']!=native['repeat'] or
                answer['arm']!=arm or native['arm']!=arm):raise ValueError('会话分段身份不符')
            for name,digest in answer['artifact_sha256'].items():
                if sha(path.parent/name)!=digest:raise ValueError('回答请求漂移')
            a,n=answer['answer_seconds'],native['query_seconds']
            if not (a>=0 and n>=0):raise ValueError('无效耗时')
            serial=a+n+plan_times[key]
            values['answer_stage'].append(a);values['native_query'].append(n)
            values['observed_serial_component_sum'].append(serial)
            unknown_sessions+=bool(unknown[key])
            rows.append({'arm':arm,'key':key,'answer_stage_seconds':a,'native_query_seconds':n,
                         'shared_planner_observed_attempt_seconds':plan_times[key],
                         'planner_attempt_elapsed_unknown_count':unknown[key],
                         'observed_serial_component_sum_seconds':serial})
            bindings[str(path.relative_to(root))]=sha(path)
            bindings[str(native_path.relative_to(root))]=sha(native_path)
        summaries[arm]={k:stats(v) for k,v in values.items()}
        summaries[arm]['sessions_with_shared_planner_unknown_elapsed']=unknown_sessions
    if args.output.exists():raise FileExistsError('需要新耗时审计版本')
    result={'schema':'closed-answer-stage-and-component-latency-v1','protocol_sha256':protocol_sha,
            'script_sha256':sha(Path(__file__)),'shared_planners':288,'answer_sessions':1728,
            'by_arm':summaries,'rows':rows,'input_sha256':bindings,'new_model_calls':0,
            'limits':'回答阶段为真实草稿至校正结束耗时，含坐标检查、等待和恢复。原生查询不含canonical渲染/共享规划/加载。规划耗时为已记录API尝试秒数；缺失秒数保留未知。分段相加是顺序请求成本估计下界，不是实测单会话端到端wall time；原运行阶段分批并发，共享规划不累计收费六次，不含构图、离线评分、图加载和所有批间空闲。p95使用nearest rank，不能相加各阶段p95形成端到端p95。'}
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':main()
