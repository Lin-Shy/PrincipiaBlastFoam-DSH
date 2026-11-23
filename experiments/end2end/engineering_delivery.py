"""Chapter-local public delivery brief and operator-side records, without scoring claims."""
import json
from pathlib import Path

DIMENSIONS = {
    'conditions': '将物理条件、允许操作与实际case及初始化实场逐项核对',
    'computation': '核验分配节点、JobID、实际终止时间、日志与原始场；退出码单独不足',
    'data_delivery': '核验原生采样、完整时间轴、单位/测点/窗口、指标复算、图和报告',
    'reproducibility': '核验输入/软件版本/命令/来源与散列；复现包齐备和实际重跑分开记录',
    'reliability': '记录失败、超时、恢复、重复提交、人工介入；单次不推断稳定率',
    'total_cost': '保留全部主/子调用、压缩、重试、工具、排队、计算及回收成本',
}

BRIEF = '''# 工程交付与资料使用边界

本任务以执行明确条件为主。conditions.json与request.md给定物理条件、目标和约束；
materials中明确列出的字典为共同提供的固定组件。raw_sources.json指向软件原始资料，
可查参数含义、字典语法和配置依据，不得据此改写任务的物理条件。
若资料与明确条件冲突，保留冲突证据；关键物理条件缺失时不得自行猜测或补设成已知事实。
任务中的条件性理想气体重建是研究者给定输入，不要求agent推断论文未知热状态。

除request.md产物外，在交付包保留以下内容（可并入同一报告，表头不要求机械一致）：
- 条件落实表：任务字段/原文位置、实际case文件与条目、单位、来源、允许修改范围。
- 来源记录：实际使用的资料相对路径、页码/段落或行段、文件SHA256、采用的结论；
  区分任务给定、资料查得与允许的数值选择，不使用评分侧材料。
- reproduce.md：软件与运行库版本、完整case、初始化/运行/采集/绘图命令和执行顺序、
  需要的资源与环境、原始输入/输出散列。仅准备重跑指令，不擅自启动额外计算。
- 原始数据到CSV/指标/图的对应关系、测点身份与时间/压力基准，失败时保留有效区间。
- observations.json记录原始数据映射：{"records":[{"sensor_id":"P1","raw_file":"raw/p","column":0}]}。
  column从零起计，不含时间列；S10测点按条件顺序命名P1/P2/P3，S12命名R0250等毫米半径编号。
  若求解器时程缺少t=0，可在计算节点独立采样初始场并保留原件及合并来源，不得编造或外推。
- 所有运行尝试与JobID、退出/异常、人工介入和未完成项。不要删除失败以得到干净目录。

外部评价分别报告条件落实、真实计算、数据交付、可复现性、可靠性与全部成本。
科学预测精度另列；证据不足写待定。可复现包齐备不等于已经独立重跑，执行正确不等于实验预测准确。
成本由操作者结合原生会话与调度账单归集；agent报告不能代替原始计量。
'''

def write_json(path, value):
    with path.open('x', encoding='utf-8') as f:
        json.dump(value, f, ensure_ascii=False, indent=2)

def public_brief(task):
    (task/'delivery.md').write_text(BRIEF,encoding='utf-8')

def operator_records(root, arms=('general','professional')):
    root.mkdir(parents=True)
    for arm in arms:
        write_json(root/(arm+'.evaluation.json'), {
            'arm':arm, 'attempt_status':'not_run', 'engineering_delivery_complete':None,
            'dimensions':{k:{'status':'not_run','criterion':v,'evidence':[]} for k,v in DIMENSIONS.items()},
            'reproduction_package':'not_assessed','independent_rerun':'not_run',
            'prediction_accuracy':{'status':'pending','reference':None,'reason':'reference/thresholds not frozen'},
            'reviewer':None, 'automatic_pass_from_files_exist':False,
        })
        write_json(root/(arm+'.cost.json'), {
            'arm':arm,'attempt_status':'not_run','events':[],
            'event_fields':['event_id','parent_event_id','kind','start_utc','end_utc','status','raw_evidence_path','raw_evidence_sha256','provider_request_id','usage','job_id','resource_usage','billed_amount','currency'],
            'event_kinds':['model_main','model_subagent','compaction','retry','tool','queue','compute','collection','manual_intervention'],
            'summary':{'model_calls':0,'cluster_jobs':0,'provider_tokens':None,'model_money':None,'compute_money':None,'elapsed_seconds':None},
            'accounting':'One provider request counted once; retain missing usage as unknown. Never add cache components twice. Separate allocated CPU-time from billing. No success-normalized cost when success count is zero.',
        })
