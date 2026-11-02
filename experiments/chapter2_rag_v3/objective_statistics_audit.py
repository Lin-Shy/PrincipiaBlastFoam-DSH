"""Rebuild closed statistics and verify that exports and viewer bind the same scores."""
import csv
import json
from pathlib import Path
import objective_experiment as exp
from objective_statistics import analyze

def check_rows_csv(path,rows):
    with path.open(encoding='utf-8-sig',newline='') as handle:
        records=list(csv.DictReader(handle))
    if len(records)!=len(rows):raise ValueError('CSV row count mismatch: '+str(path))
    for record,row in zip(records,rows):
        for key,value in row.items():
            expected='' if value is None else str(value)
            if record[key]!=expected:raise ValueError(f'CSV mismatch {path} {row.get("id")} {key}')

def main():
    manifest=exp.verify();outputs=[]
    for label,root in [('strict',exp.OUT),('supplementary',exp.OUT/'supplementary_parser')]:
        rows=exp.read(root/'scores/per_answer.json');snapshot=exp.read(root/'results/snapshot.json')
        if snapshot['status']!='closed' or len(rows)!=manifest['tasks']:
            raise ValueError('closed complete snapshot required')
        if analyze(rows,manifest['analysis'])!=snapshot['statistics']:
            raise ValueError(label+' statistics mismatch')
        check_rows_csv(root/'results/per_answer.csv',rows)
        check_rows_csv(root/'results/summary.csv',snapshot['configurations'])
        page=(root/'results/index.html').read_text(encoding='utf8')
        data=json.loads(page.split('<script>const DATA=',1)[1].split(';\nconst esc=',1)[0])
        if data['snapshot']!=snapshot or len(data['rows'])!=len(rows):raise ValueError(label+' page mismatch')
        for source,displayed in zip(rows,data['rows']):
            if any(source[k]!=displayed[k] for k in ('config_id','id','score','reason','raw_answer')):
                raise ValueError(label+' displayed response mismatch')
        outputs.append(dict(label=label,rows=len(rows),snapshot_sha256=exp.sha(root/'results/snapshot.json'),
                            page_sha256=exp.sha(root/'results/index.html')))
    audit=dict(status='passed',outputs=outputs,code_sha256=exp.sha(Path(__file__)))
    exp.save(exp.OUT/'results/statistics_audit.json',audit)
    print('statistics and display audit: passed',len(outputs),'snapshots')

if __name__=='__main__':main()
