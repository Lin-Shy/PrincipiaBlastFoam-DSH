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
    for route,root,normalizer in [('chat_sse',c.ROOT,chat),('native_responses',c.ROOT/'native',native)]:
        for reqfile in root.glob('controls/*/*/attempt_*/request.json'):
            folder=reqfile.parent;req=c.core.read(reqfile);state=c.core.read(folder/'status.json') if (folder/'status.json').exists() else {}
            rejection=normalizer.rejection((folder/'response.sse').read_text(encoding='utf-8')) if (folder/'response.sse').exists() else None
            parsed=c.core.read(folder/'parsed.json') if (folder/'parsed.json').exists() else None
            status='valid_synthetic_control' if parsed else 'explicit_provider_overload' if rejection else 'transport_unresolved'
            headers=state.get('headers',{})
            rid=next((v for k,v in headers.items() if k.lower()=='x-request-id'),None)
            rows.append(dict(route=route,effort=folder.parent.parent.name,sample_id=folder.parent.name,attempt=folder.name,
                status=status,http_status=state.get('http_status'),started_utc=state.get('started_utc'),completed_utc=state.get('completed_utc'),request_id=rid,
                request_model=req['request']['body']['model'],response_model=parsed.get('response_model') if parsed else rejection.get('response_model') if rejection else None,
                request_sha256=req['request_sha256'],request_path=str(reqfile.relative_to(c.core.DEFAULT_RUN)),
                error=state.get('reason'),provider_message=rejection.get('message') if rejection else None,
                retry_without_reconciliation=bool(rejection)))
    rows.sort(key=lambda r:(r['route'],r['effort'],r['sample_id'],r['attempt']))
    out=c.ROOT/'reconciliation.csv'
    with out.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    counts=dict(Counter(r['status'] for r in rows))
    report=dict(utc=c.stream.terra.s.now(),model='gpt-6.1-terra',requests=len(rows),states=counts,
        human_calibration_requests=len(list(c.ROOT.glob('calibration/*/*/attempt_*/request.json')))+len(list((c.ROOT/'native').glob('calibration/*/*/attempt_*/request.json'))),
        new_audit_requests=len(list(c.ROOT.glob('audit/*/*/attempt_*/request.json')))+len(list((c.ROOT/'native').glob('audit/*/*/attempt_*/request.json'))),
        human_acceptance=False,formal_sol_replacement=False,decision='service_blocked_before_calibration',
        explanation='Explicit upstream overload and unresolved connections prevent positive controls closing. Returned negative controls are correct. No human-score threshold or Prompt changed.',
        evidence_sha256={str(p.relative_to(c.ROOT)):c.core.sha(p) for p in c.ROOT.glob('**/*') if p.is_file() and p.name in ('request.json','status.json','response.sse','response.txt','parsed.json','provider_rejection_resolution.json','provider_diagnostics.json')})
    c.stream.terra.s.save(c.ROOT/'diagnostics.json',report)
    h=['<html lang="zh-CN"><meta charset="utf-8"><title>Terra接口与候选配置诊断</title><body style="font:16px/1.7 system-ui;max-width:1250px;margin:30px auto"><h1>Terra接口与候选配置诊断</h1>',
       '<p>已测试Chat流式与原生Responses两种接口，以及medium/high推理强度。'+str(len(rows))+'次技术请求：'+escape(str(counts))+'。</p>',
       '<p>返回的反向事实/条件控制评分正确；正向控制仍有未决。以上仅为合成接口控制，不是人工可靠性审计。供应商明确报告上游过载，尚未进入新18答校准或锁定12答审计，未替换Sol。</p>',
       '<p>已实现严格流重建、原始SSE保存、精确模型与usage校验、32K额度控制、明确过载退避重试。无回执断连不重发；旧30答验证与原Sol结果保持原始身份。</p>',
       '<p><a href="reconciliation.csv">供应商核对清单</a> · <a href="diagnostics.json">原始证据哈希</a> · <a href="../terra_validation/index.html">旧固定30答验证</a></p>',
       '<table border="1" cellpadding="6" style="border-collapse:collapse;font-size:13px"><tr><th>接口</th><th>推理</th><th>样本</th><th>尝试</th><th>状态</th><th>HTTP</th><th>供应商请求ID</th></tr>']
    for r in rows:h.append('<tr>'+''.join('<td>'+escape(str(r[k] or ''))+'</td>' for k in ['route','effort','sample_id','attempt','status','http_status','request_id'])+'</tr>')
    h.append('</table><p>继续执行前，应由供应商核对CSV中的请求ID、时间及请求哈希，补回未决真实响应或确认未执行。仅服务已恢复不能证明旧请求未执行。</p></body></html>')
    (c.ROOT/'index.html').write_text('\n'.join(h),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='evidence_sha256'},ensure_ascii=True))


if __name__=='__main__':run()
