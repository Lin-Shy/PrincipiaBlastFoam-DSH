"""Current standalone joint K/F/A page builder. No audit input is read."""
import json
from pathlib import Path
from judge_contract import RULES, VERSION
HERE=Path(__file__).parent

def build_page(prepared):
    from scoring import ROOT, read
    audit=prepared.get('batch')=='audit'
    data=dict(schema_version=VERSION,packet_id=prepared['packet_id'],items=prepared['items'],ui=prepared['ui'],rules=RULES,
        batch='audit' if audit else 'calibration',audit_included=audit,human_blind=audit)
    data['saved']=read(ROOT/'human/draft.json') if (ROOT/'human/draft.json').exists() else None
    payload=json.dumps(data,ensure_ascii=False).replace('<','\\u003c').replace('\u2028','\\u2028').replace('\u2029','\\u2029')
    html=(HERE/'human_unified_template.html').read_text(encoding='utf-8').replace('__PACKET_JSON__',payload).replace('__APPLICATION_JS__',(HERE/'human_unified.js').read_text(encoding='utf-8'))
    if audit:
        html=html.replace('第2章 · 五档 K/F/A 联合评分','第2章 · 独立审计 K/F/A 联合评分').replace('Dev校准6题18答','独立审计4题12答 · 不展示AI评分')
    target=ROOT/('index.html' if audit else 'human/index.html');target.parent.mkdir(parents=True,exist_ok=True);target.write_text(html,encoding='utf-8')
    return target

if __name__=='__main__':
    from scoring import load
    print(build_page(load()))
