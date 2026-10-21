"""Compare actual dev judge results to prior masked AI review, keeping unknowns."""
import argparse
import hashlib
import json
from pathlib import Path
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--review',type=Path,required=True)
    p.add_argument('--scores',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if a.output.exists():raise FileExistsError('comparison revision is immutable')
    expected=read(a.review);protocol=read(a.scores/'protocol.json');observed={};bindings={}
    for path in a.scores.glob('sessions/*/score.json'):
        score=read(path);qid=score['question_id']
        if qid in observed:raise ValueError('duplicate actual review question score')
        if score['protocol_sha256']!=sha(a.scores/'protocol.json'):raise ValueError('judge protocol binding drift')
        observed[qid]=score;bindings[qid]=sha(path)
    rows=[]
    for e in expected['verdicts']:
        s=observed.get(e['question_id']);m=s.get('metrics',{}) if s else {};auto=m.get('complete_valid_answer');reference=e['complete_valid_answer']
        lower=int(reference==auto) if reference is not None and auto is not None else 0
        upper=lower if reference is not None and auto is not None else 1
        by_point={p['id']:p for p in s.get('judgment',{}).get('points',[])} if s else {}
        differences=[]
        for point in e['required_points']:
            actual=by_point.get(point['id'])
            if not actual or actual['verdict']!=point['verdict']:
                differences.append({'point_id':point['id'],'ai_review_verdict':point['verdict'],
                  'judge_verdict':actual.get('verdict') if actual else None,'judge_reason':actual.get('reason') if actual else None})
        rows.append({'review_id':e['review_id'],'question_id':e['question_id'],'ai_review_complete':reference,
          'judge_complete':auto,'agreement_lower':lower,'agreement_upper':upper,'required_point_differences':differences,
          'score_sha256':bindings.get(e['question_id']),'status':s['status'] if s else 'pending'})
    n=len(rows);known=[r for r in rows if r['ai_review_complete'] is not None]
    result={'schema':'masked_actual_development_answer_comparison_v1','formal_result':False,'human_truth':False,
      'review_sha256':sha(a.review),'judge_protocol_sha256':sha(a.scores/'protocol.json'),'implementation_sha256':sha(Path(__file__)),
      'questions':n,'known_ai_reference_questions':len(known),'unknown_ai_reference_questions':n-len(known),
      'all_question_agreement_lower':sum(r['agreement_lower'] for r in rows)/n,
      'all_question_agreement_upper':sum(r['agreement_upper'] for r in rows)/n,
      'known_ai_reference_matches':sum(r['agreement_lower'] for r in known),'rows':rows,
      'semantic_point_differences_require_review':sum(len(r['required_point_differences']) for r in rows),
      'formal_judge_freeze_authorized':False,'limitations':['Both reference and judge are AI judgments, not human truth.',
        'Ambiguous reference cases remain in the full denominator with [0,1] agreement bounds.',
        'Primary binary agreement does not prove point coverage, source interpretation or condition judgments are all accurate.']}
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:result[k] for k in ('questions','known_ai_reference_questions','known_ai_reference_matches','all_question_agreement_lower','all_question_agreement_upper','semantic_point_differences_require_review','formal_judge_freeze_authorized')}))
if __name__=='__main__':main()
