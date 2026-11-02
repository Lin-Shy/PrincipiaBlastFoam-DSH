"""Describe pre-existing paired multiple-choice and judgment facts."""
import html
from pathlib import Path
import objective_experiment as exp

def main():
    m=exp.verify(); strict=exp.read(exp.OUT/'scores/per_answer.json')
    out=exp.OUT/'supplementary_parser';alternate=exp.read(out/'scores/per_answer.json')
    s=exp.read(exp.OUT/'results/snapshot.json');t=exp.read(out/'results/snapshot.json')
    if s['completed']!=t['completed'] or exp.sha(exp.OUT/'scores/per_answer.json')!=t['source_strict_sha256']:
        raise ValueError('scoring snapshots are not aligned')
    gold={g['id']:g for g in exp.read(exp.DATA/'scoring/annotations.json')}
    pairs=[(f'OBJ-{i:03d}',f'OBJ-{i+50:03d}') for i in range(93,123)]
    for left,right in pairs:
        l=gold[left]['evidence'][0];r=gold[right]['evidence'][0]
        if (l['path'],l['start'])!=(r['path'],r['start']):raise ValueError('paired source mismatch')
    result=[]
    for name,rows in [('strict',strict),('supplementary',alternate)]:
        lookup={(r['config_id'],r['id']):r for r in rows}
        for c in m['configurations']:
            counts={'both_correct':0,'single_only':0,'judge_only':0,'neither':0,'pending':0}
            for left,right in pairs:
                x=lookup[c['config_id'],left]['score'];y=lookup[c['config_id'],right]['score']
                if x is None or y is None:counts['pending']+=1
                elif x and y:counts['both_correct']+=1
                elif x:counts['single_only']+=1
                elif y:counts['judge_only']+=1
                else:counts['neither']+=1
            result.append(dict(scoring=name,model=c['logical_model'],method=c['method_id'],**counts))
    destination=exp.OUT/'analysis/format_pairs.csv';exp.export_csv(destination,result)
    summary=dict(created=exp.now(),status=s['status'],pairs_per_config=len(pairs),
        interpretation='Descriptive paired formats share facts; neither set is independent. No significance claim.',
        strict_snapshot_sha256=exp.sha(exp.OUT/'results/snapshot.json'),
        supplementary_snapshot_sha256=exp.sha(out/'results/snapshot.json'),csv_sha256=exp.sha(destination),
        code_sha256=exp.sha(Path(__file__)))
    exp.save(exp.OUT/'analysis/format_pairs_provenance.json',summary)
    cols=['scoring','model','method','both_correct','single_only','judge_only','neither','pending']
    table=''.join('<tr>'+''.join('<td>'+html.escape(str(r[k]))+'</td>' for k in cols)+'</tr>' for r in result)
    page='<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>客观题跨题型配对</title><style>body{font:16px system-ui;margin:30px auto;max-width:1100px}table{border-collapse:collapse;width:100%}th,td{padding:8px;border-bottom:1px solid #ddd;text-align:left}</style><h1>单选与判断的共享事实配对</h1><p>每配置30对；统计同一事实的两题答对情况。两题关联，不能算两个独立事实。严格规则和事后补充解析分别列出；未完成配对单列。</p><p><a href="../results/index.html">返回客观题结果</a> · <a href="format_pairs.csv">CSV</a></p><table><tr>'+''.join('<th>'+html.escape(k)+'</th>' for k in cols)+'</tr>'+table+'</table></html>'
    (destination.parent/'format_pairs.html').write_text(page,encoding='utf8',newline='\n')
    print('paired format analysis generated:',s['status'],len(result),'configuration/rule rows')

if __name__=='__main__':main()
