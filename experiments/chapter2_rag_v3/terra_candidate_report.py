"""Read-only interface diagnostics. Synthetic controls are never human reliability evidence."""
import csv
from html import escape
import json
from pathlib import Path
from collections import Counter
import terra_candidate as c
import terra_native as native
import terra_stream as chat


def run():
    rows=[]
    for route,root,normalizer in [('chat_sse',c.ROOT,chat),('native_responses',c.ROOT/'native',native),('chat_sse_serial',c.ROOT/'latency',chat),('native_foreground_validation',c.ROOT/'foreground/validation',native)]:
        for phase,reqfile in [(phase,p) for phase in ('controls','calibration','audit') for p in root.glob(phase+'/*/*/attempt_*/request.json')]:
            folder=reqfile.parent;req=c.core.read(reqfile);state=c.core.read(folder/'status.json') if (folder/'status.json').exists() else {}
            rejection=normalizer.rejection((folder/'response.sse').read_text(encoding='utf-8')) if (folder/'response.sse').exists() else None
            parsed=c.core.read(folder/'parsed.json') if (folder/'parsed.json').exists() else None
            status=('valid_synthetic_control' if phase=='controls' else 'valid_human_reference_grade') if parsed else 'explicit_provider_overload' if rejection else 'explicit_http_rejection' if state.get('http_status',200)!=200 else 'in_progress' if not state.get('completed_utc') else 'transport_unresolved'
            headers=state.get('headers',{})
            rid=next((v for k,v in headers.items() if k.lower()=='x-request-id'),None)
            rows.append(dict(route=route,phase=phase,effort=folder.parent.parent.name,sample_id=folder.parent.name,attempt=folder.name,
                status=status,http_status=state.get('http_status'),started_utc=state.get('started_utc'),completed_utc=state.get('completed_utc'),request_id=rid,
                request_model=req['request']['body']['model'],response_model=parsed.get('response_model') if parsed else rejection.get('response_model') if rejection else None,
                request_sha256=req['request_sha256'],request_path=str(reqfile.relative_to(c.core.DEFAULT_RUN)),
                error=state.get('reason'),provider_message=rejection.get('message') if rejection else None,
                retry_without_reconciliation=bool(rejection)))
    for route in ('background','foreground'):
        folder=c.ROOT/route
        if not (folder/'request.json').exists():continue
        req=c.core.read(folder/'request.json');state=c.core.read(folder/'status.json')
        message=None
        if (folder/'receipt.txt').exists():
            try:message=json.loads((folder/'receipt.txt').read_text(encoding='utf-8')).get('error',{}).get('message')
            except (ValueError,AttributeError):pass
        parsed=c.core.read(folder/'parsed.json') if (folder/'parsed.json').exists() else None
        status='valid_synthetic_control' if parsed else 'explicit_unsupported_parameter' if message and 'Unsupported parameter' in message else 'explicit_http_rejection' if state.get('http_status',200)!=200 else 'transport_unresolved'
        rows.append(dict(route=route,phase='controls',effort=req['request']['body']['reasoning']['effort'],sample_id='TC_correct',attempt='probe_1',
            status=status,http_status=state.get('http_status'),started_utc=state.get('started_utc'),completed_utc=state.get('completed_utc'),
            request_id=next((v for k,v in state.get('headers',{}).items() if k.lower()=='x-request-id'),None),
            request_model=req['request']['body']['model'],response_model=parsed.get('response_model') if parsed else None,
            request_sha256=req['request']['request_sha256'],request_path=str((folder/'request.json').relative_to(c.core.DEFAULT_RUN)),
            error=state.get('reason'),provider_message=message,retry_without_reconciliation=False))
    rows.sort(key=lambda r:(r['route'],r['effort'],r['sample_id'],r['attempt']))
    out=c.ROOT/'reconciliation.csv'
    with out.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    counts=dict(Counter(r['status'] for r in rows))
    calibration_requests=list(c.ROOT.glob('**/calibration/*/*/attempt_*/request.json'))
    audit_requests=list(c.ROOT.glob('**/audit/*/*/attempt_*/request.json'))
    gate_path=c.ROOT/'foreground/validation/selected/results.json'
    if not gate_path.exists():gate_path=c.ROOT/'foreground/validation/report/results.json'
    gate=c.core.read(gate_path) if gate_path.exists() else {}
    report=dict(utc=c.stream.terra.s.now(),model='gpt-6.1-terra',requests=len(rows),states=counts,
        technical_control_requests=sum(r['phase']=='controls' for r in rows),
        human_calibration_requests=len(calibration_requests),
        new_audit_requests=len(audit_requests),
        human_acceptance=bool(gate.get('accepted')),formal_sol_replacement=False,decision=gate.get('decision','human_reference_validation_in_progress' if calibration_requests else 'controls_not_closed'),
        explanation='Four reasoning settings, serial dispatch and native routes tested. Native nonstream JSON returned a correct positive control; background explicitly unsupported. Human-reference quality gate remains separate. No threshold or Prompt changed.',
        evidence_sha256={str(p.relative_to(c.ROOT)):c.core.sha(p) for p in c.ROOT.glob('**/*') if p.is_file() and p.name in ('request.json','status.json','response.sse','response.txt','parsed.json','receipt.txt','official_evidence.json','provider_rejection_resolution.json','provider_diagnostics.json')})
    c.stream.terra.s.save(c.ROOT/'diagnostics.json',report)
    h=['<html lang="zh-CN"><meta charset="utf-8"><title>Terra接口与候选配置诊断</title><body style="font:16px/1.7 system-ui;max-width:1250px;margin:30px auto"><h1>Terra接口与候选配置诊断</h1>',
       '<p>已测试Chat流式与原生Responses，以及none/low/medium/high推理强度、串行调度和后台模式。'+str(len(rows))+'次模型请求（包含技术控制与人工参考评分）：'+escape(str(counts))+'。</p>',
       '<p>原生非流式JSON正向控制已返回正确评分；其他未决保持原身份。合成控制不是人工可靠性审计。新校准请求'+str(len(calibration_requests))+'次，复核请求'+str(len(audit_requests))+'次；人工参考验收状态为'+escape(str(report['human_acceptance']))+'，尚未替换Sol。原12答已被观察，重复复核不构成新的独立未见审计。</p>',
       '<p>已实现严格流重建、原始SSE保存、精确模型与usage校验、32K额度控制、明确过载退避重试。后台模式被当前代理明确拒绝；无回执断连不重发。旧30答验证与原Sol结果保持原始身份。</p>',
       '<p><a href="reconciliation.csv">供应商核对清单</a> · <a href="diagnostics.json">原始证据哈希</a> · <a href="../terra_validation/index.html">旧固定30答验证</a></p>',
       '<table border="1" cellpadding="6" style="border-collapse:collapse;font-size:13px"><tr><th>接口</th><th>推理</th><th>样本</th><th>尝试</th><th>状态</th><th>HTTP</th><th>供应商请求ID</th></tr>']
    if (c.ROOT/'foreground/validation/report/index.html').exists():
        h.insert(-1,'<p><a href="foreground/validation/report/index.html">原生JSON固定30答验证、缺评界限及逐回答数据</a></p>')
    for r in rows:h.append('<tr>'+''.join('<td>'+escape(str(r[k] or ''))+'</td>' for k in ['route','effort','sample_id','attempt','status','http_status','request_id'])+'</tr>')
    h.append('</table><p>继续执行前，应由供应商核对CSV中的请求ID、时间及请求哈希，补回未决真实响应或确认未执行。仅服务已恢复不能证明旧请求未执行。</p></body></html>')
    (c.ROOT/'index.html').write_text('\n'.join(h),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='evidence_sha256'},ensure_ascii=True))


if __name__=='__main__':run()
