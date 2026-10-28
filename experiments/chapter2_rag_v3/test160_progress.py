"""Status-only public HTML; deliberately never reads labels or scores."""
import html
import json
from pathlib import Path
import single_pass_dev40 as s


def render(status):
    out=s.RUN/'results'
    body='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta http-equiv="refresh" content="60"><title>第2章 Test160 正式执行</title><style>body{font:16px system-ui;max-width:1180px;margin:36px auto;padding:0 24px;color:#20334b;background:#fafbfd}h1{font-size:30px}table{border-collapse:collapse;width:100%;background:white}td,th{padding:12px;border-bottom:1px solid #dfe6ed;text-align:left}a{color:#12698c}.note{padding:16px;background:#edf4f8;border-left:4px solid #12698c}small{color:#546478}</style><h1>Test160 正式实验正在执行</h1><p>已获负责人一次性完整授权：4160 条 Agentic、960 条 Single-Pass，GPT-6 Sol 与 DeepSeek V4.1 Flash 独立双评。</p><p class="note">此页仅报告运行状态。尚未完成的实验不形成论文结论；固定分母保留，服务挂起的未发送任务不视为生成失败。原独立人工审计未达到最初严格门槛，该事实保持不变。</p>'''
    body+='<p><a href="../README.md">正式说明</a> · <a href="../test160_runs/controller_status.json">机器可读进度</a> · <a href="../test160_runs/execution_events.jsonl">生成请求事件</a> · <a href="../release/protocol/test160_approval.json">授权绑定</a> · <a href="dev40.html">Dev40 冻结结果</a></p>'
    body+='<table><tr><th>模式 / 模型</th><th>终态 / 固定分母</th><th>状态分布</th></tr>'
    for mode in ['agentic','single_pass']:
        for model in ['qwen3_8b','qwen3_14b']:
            v=status[mode+'|'+model]
            body+='<tr><td>'+mode+' / '+model+'</td><td>'+str(v['terminal'])+' / '+str(v['expected'])+'</td><td>'+html.escape(json.dumps(v['states'],ensure_ascii=False))+'</td></tr>'
    body+='</table><h2>双裁判流水线</h2><table><tr><th>模式</th><th>已绑定回答</th><th>评价处理状态</th></tr>'
    for mode,prefix in [('agentic',s.RUN/'test160_runs'),('single_pass',s.RUN/'test160_runs/supplement/single_pass')]:
        p=prefix/'scoring/stream_status.json';v=s.load(p) if p.exists() else {}
        body+='<tr><td>'+mode+'</td><td>'+str(v.get('bound_answers',0))+'</td><td>'+html.escape(json.dumps(v.get('states',{}),ensure_ascii=False))+'</td></tr>'
    body+='</table><p><small>更新时间：'+html.escape(status['updated_utc'])+'。每 60 秒自动刷新。评分不反馈给生成或参数选择。</small></p></html>'
    (out/'index.html').write_text(body,encoding='utf-8')


if __name__=='__main__':
    render(s.load(s.RUN/'test160_runs/controller_status.json'))
