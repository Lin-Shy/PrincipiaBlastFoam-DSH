"""Apply evidence-backed objective experiment updates to current manuscript and shared design."""
from pathlib import Path
import objective_experiment as exp

BEGIN='% OBJECTIVE-20261102-BEGIN'
END='% OBJECTIVE-20261102-END'

def insert_before(text,anchor,content):
    if BEGIN in text:raise ValueError('objective update already present')
    if text.count(anchor)!=1:raise ValueError('expected unique anchor: '+anchor)
    return text.replace(anchor,BEGIN+'\n'+content+'\n'+END+'\n\n'+anchor,1)

def insert_after(text,anchor,content):
    if BEGIN in text:raise ValueError('objective update already present')
    if text.count(anchor)!=1:raise ValueError('expected unique anchor: '+anchor)
    return text.replace(anchor,anchor+'\n'+BEGIN+'\n'+content+'\n'+END,1)

def main():
    s=exp.read(exp.OUT/'results/snapshot.json');alt=exp.read(exp.OUT/'supplementary_parser/results/snapshot.json')
    audit=exp.read(exp.OUT/'results/statistics_audit.json')
    if s['status']!='closed' or alt['status']!='closed' or audit['status']!='passed':raise ValueError('closed audited snapshots required')
    if {x['snapshot_sha256'] for x in audit['outputs']}!={exp.sha(exp.OUT/'results/snapshot.json'),exp.sha(exp.OUT/'supplementary_parser/results/snapshot.json')}:
        raise ValueError('statistics audit is stale')
    def accuracy(model):
        return next(x['accuracy'] for x in s['configurations'] if x['model']==model and x['method']=='graph')*100
    n=s['planned'];a=accuracy('qwen3-8b');b=accuracy('qwen3-14b')
    man=exp.WORK/'graduation-thesis-materials/graduation-manuscript';research=exp.WORK/'graduation-thesis-materials/graduation-research'
    paths={x:man/'docs'/x for x in ('chap02.tex','abstract.tex','chap05.tex','appendix_ch02.tex')}
    updates={}
    updates[paths['chap02.tex']]=insert_after(paths['chap02.tex'].read_text(encoding='utf8'),r'\input{docs/chap02_knowledge_qa_results.tex}',r'\input{docs/chap02_objective_results.tex}')
    p=paths['abstract.tex'];text=p.read_text(encoding='utf8')
    chinese=f'另以172道客观题补充评价，两模型各比较13种配置，共{n}项任务；冻结规则下8B与14B完整图准确率分别为{a:.2f}\\%和{b:.2f}\\%。题目未经独立领域专家审核，部分题目共享事实；格式要求的影响另以事后统一解析报告。'
    english=f'An additional 172-item objective set yields {n} tasks across 13 configurations per model. Under the frozen rule, full-graph accuracy is {a:.2f}\\% for 8B and {b:.2f}\\% for 14B. Items were not independently reviewed by domain experts, some share facts, and a post hoc uniform parser assesses sensitivity to answer format.'
    # One marked block per file; place Chinese and English content adjacent to their own paragraphs.
    ca='\n14B完整图自主模式的算术与几何EAS';ea='\nWith 14B, full-graph Agentic arithmetic/geometric EAS'
    if text.count(ca)!=1 or text.count(ea)!=1:raise ValueError('abstract anchors changed')
    text=text.replace(ca,'\n'+BEGIN+'\n'+chinese+'\n'+END+'\n'+ca,1).replace(ea,'\n'+english+'\n'+ea,1)
    updates[p]=text
    p=paths['chap05.tex'];updates[p]=insert_before(p.read_text(encoding='utf8'),'其次，既有blastFoam仿真工作流',
        f'客观题补充评价覆盖172题和{n}个任务，冻结规则下8B和14B完整图准确率分别为{a:.2f}\\%与{b:.2f}\\%。客观准确率与开放问答EAS分别解释；题目共享事实、缺少独立领域专家复核以及事后格式敏感性分析限制了结论。')
    p=paths['appendix_ch02.tex'];updates[p]=insert_before(p.read_text(encoding='utf8'),r'\section{正式运行与来源绑定}',
        r'\section{客观题补充实验的来源与审计}'+'\n\n'+
        r'独立批次位于\path{graduation-experiment-results/chapter2_retrieval/objective200/}。\path{manifest_public.json}保留公开协议及冻结文件哈希；本地私有Manifest和原始请求记录保留部署身份。\path{results/per_answer.csv}、\path{results/summary.csv}和\path{results/snapshot.json}分别提供逐答、配置汇总与统计；\path{results/closure_audit.json}和\path{results/statistics_audit.json}核验逐答评分及统计、导出和页面一致性。事后补充解析保存在\path{supplementary_parser/}，其规则和结果不替换冻结主分析。原始文件哈希清单位于\path{results/raw_inventory.jsonl}，不复制私有端点。')
    desc=f'2026-11-02客观题补充批次已完成：172题（填空60、短答32、单选50、判断30），两模型各13种配置，共{n}个任务。固定分母准确率与原开放问答EAS分开报告；8B使用超算部署，14B使用代理。30组单选与判断共享事实，题目经过本地AI来源复核但未完成独立领域专家审核。冻结规则和事后统一单行解析分开呈现。论文正文和PDF按实验闭合快照同步，验收结果见实验目录。下方旧状态保留历史身份，以本段及正式实验入口为当前补充状态。'
    for p in (research/'README.md',research/'OVERVIEW.md',research/'chapters/chapter02.md'):
        text=p.read_text(encoding='utf8');first,rest=text.split('\n',1)
        if BEGIN in text:raise ValueError('objective update already present: '+str(p))
        updates[p]=first+'\n\n'+BEGIN+'\n## 第2章客观题补充实验（2026-11-02）\n\n'+desc+'\n'+END+'\n'+rest
    for p,value in updates.items():p.write_text(value,encoding='utf8',newline='\n')
    print('updated',len(updates),'manuscript and design files')

if __name__=='__main__':main()
