"""Bind valid development inputs before calculating judge calibration rates."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

def read(p):return json.loads(p.read_text(encoding='utf-8'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def summarize(expected,observations):
    by_id={r['control_id']:r for r in expected['controls']}
    if len(by_id)!=len(expected['controls']):raise ValueError('duplicate expected control IDs')
    grouped={};invalid=[]
    for obs in observations:
        cid=obs['control_id']
        if cid not in by_id:raise ValueError('unplanned calibration control')
        if not obs['candidate_matches_expected']:
            invalid.append(obs);continue
        if cid in grouped:raise ValueError('same valid candidate scored twice; quality retries cannot enter this calibration')
        grouped[cid]=obs
    rows=[]
    for cid,e in sorted(by_id.items()):
        obs=grouped.get(cid);value=obs.get('complete') if obs else None
        if value not in (0,1,None):raise ValueError('invalid complete verdict')
        rows.append({'control_id':cid,'question_id':e['question_id'],'type':e['type'],'expected_complete':e['expected_complete'],
          'observed_complete':value,'parsed':bool(obs and obs['status']=='judged'),
          'agreement_lower':int(value==e['expected_complete']) if value is not None else 0,
          'agreement_upper':int(value==e['expected_complete']) if value is not None else 1,
          'score_file_sha256':obs.get('score_file_sha256') if obs else None,
          'reason':obs.get('reason') if obs else 'pending','point_review_flags':obs.get('point_review_flags',[]) if obs else []})
    def rates(rs):
        n=len(rs)
        return {'controls':n,'parsed':sum(r['parsed'] for r in rs),'parse_rate':sum(r['parsed'] for r in rs)/n,
          'complete_agreement_lower':sum(r['agreement_lower'] for r in rs)/n,
          'complete_agreement_upper':sum(r['agreement_upper'] for r in rs)/n,
          'unknown_or_pending':sum(r['observed_complete'] is None for r in rs)}
    overall=rates(rows);classes={k:rates([r for r in rows if r['type']==k]) for k in sorted({r['type'] for r in rows})}
    criteria=expected['acceptance_before_scoring'];threshold_passed=overall['controls']>=criteria['min_controls'] and len({r['question_id'] for r in rows})>=criteria['min_questions'] and overall['parse_rate']>=criteria['minimum_parse_rate'] and overall['complete_agreement_lower']>=criteria['minimum_all_control_complete_agreement'] and all(c['complete_agreement_lower']>=criteria['minimum_per_class_agreement'] for c in classes.values())
    return {'schema':'bound_development_judge_calibration_v1','formal_result':False,'human_truth':False,'overall':overall,
      'by_class':classes,'rows':rows,'invalid_input_observations':invalid,'acceptance_criteria':criteria,
      'numeric_thresholds_passed':threshold_passed,'semantic_review_complete':False,
      'ready_for_formal_judge_freeze':False,'limits':['Control expectations are AI source judgments, not human truth.',
        'All planned controls remain denominators. Invalid input attempts are recorded separately; missing valid judgments remain unknown.',
        'Numeric acceptance alone cannot replace source review of point disagreements and blinded actual-development-answer audit.']}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--expected',type=Path,required=True)
    p.add_argument('--score-root',type=Path,action='append',required=True);p.add_argument('--result-root',type=Path,action='append',required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if len(a.score_root)!=len(a.result_root):raise ValueError('each scoring root needs its original result root')
    if a.output.exists():raise FileExistsError('calibration report revision is immutable')
    expected=read(a.expected);controls={r['control_id']:read(a.expected.parent/'generation/sessions'/r['control_id']/'result.json') for r in expected['controls']}
    observations=[];protocols=[];identity=None
    for score_root,result_root in zip(a.score_root,a.result_root):
        protocol=read(score_root/'protocol.json')
        current=(protocol['judge_model'],protocol['rubric_version'],protocol['judge_prompt'],protocol['source_sha256'])
        if identity is not None and identity!=current:raise ValueError('different judge designs cannot be silently combined')
        identity=current;protocols.append({'score_root':str(score_root),'protocol_sha256':sha(score_root/'protocol.json')})
        for path in sorted(score_root.glob('sessions/*/score.json')):
            score=read(path);relative=score['result_relative_path'];result_path=result_root/relative
            if not result_path.resolve().is_relative_to(result_root.resolve()):raise ValueError('result path escapes calibration input')
            if sha(result_path)!=score['result_sha256'] or protocol['result_bindings'].get(relative)!=sha(result_path):raise ValueError('control result binding drift')
            result=read(result_path);cid=result_path.parent.name;target=controls[cid]
            matches=result['answer']==target['answer'] and result['question']==target['question']
            flags=[]
            if cid.endswith('_positive'):
                flags=[{'point_id':r['id'],'verdict':r['verdict'],'reason':r['reason']} for r in score.get('judgment',{}).get('points',[]) if r['verdict']!='satisfied']
            observations.append({'control_id':cid,'candidate_matches_expected':matches,'score_file_sha256':sha(path),
              'status':score['status'],'reason':score.get('reason'),'complete':score.get('metrics',{}).get('complete_valid_answer'),
              'point_review_flags':flags,'score_path':str(path)})
    report=summarize(expected,observations)
    report.update(expected_sha256=sha(a.expected),judge_protocol_bindings=protocols,implementation_sha256=sha(Path(__file__)))
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'overall':report['overall'],'by_class':report['by_class'],'invalid_inputs':len(report['invalid_input_observations']),
      'numeric_thresholds_passed':report['numeric_thresholds_passed'],'ready_for_formal_judge_freeze':False}))

if __name__=='__main__':main()
