"""Prospective, masked source/citation review for the complete new matrix."""
import argparse
from datetime import datetime, timezone
from pathlib import Path
import secrets

from chapter2_full_protocol import validate, selected_cases, verify_dataset, verify_result
from chapter2_v2_retrieval_probe import read, save, sha
from chapter2_knowledge_formal_plan import digest
from chapter2_knowledge_formal_review import masked_item, validate_verdicts
from chapter2_citation_original_review import masked_case, validate_review


def verify_selection(selection, plan, plan_sha):
    if selection.get('schema') != 'complete_knowledge_qa_review_selection_v4' or selection.get('plan_sha256') != plan_sha:
        raise ValueError('Review selection belongs to another plan')
    if [(r['cell_id'],r['question_id']) for r in selection['cases']] != selected_cases(plan):
        raise ValueError('Prospective review cohort changed')
    ids = [r['review_id'] for r in selection['cases']]
    if len(set(ids)) != len(ids) or any(len(v)!=32 or any(c not in '0123456789abcdef' for c in v) for v in ids):
        raise ValueError('Unique opaque review IDs required')
    return selection


def load_reviews(root, plan, plan_sha, generation, selection_path):
    """Only completed, bound packs authorize source-first automatic grading."""
    selection = verify_selection(read(selection_path),plan,plan_sha)
    expected = {r['review_id']:(r['cell_id'],r['question_id']) for r in selection['cases']}
    opinions = {}; citations = {}; provenance = {}
    for folder in sorted(Path(root).glob('pack_*')):
        answer_file = folder/'evaluation_only/answer-verdicts.json'
        citation_file = folder/'evaluation_only/citation-verdicts.json'
        if not answer_file.exists() or not citation_file.exists():continue
        receipt = read(folder/'pack-receipt.json')
        if receipt['plan_sha256'] != plan_sha or receipt['selection_sha256'] != sha(selection_path):raise ValueError('Review pack belongs to another activity')
        inputs_path = folder/'evaluation_only/answer-inputs.json'; citation_path = folder/'evaluation_only/citation-inputs.json'
        key_path = folder/'evaluation_only/blind-key.json'
        for name,path in [('answer_inputs_sha256',inputs_path),('citation_inputs_sha256',citation_path),('blind_key_sha256',key_path)]:
            if receipt[name] != sha(path):raise ValueError('Review pack integrity changed')
        inputs = read(inputs_path); key = read(key_path)
        values = validate_verdicts(read(answer_file),[r['review_id'] for r in inputs])
        by_id = {r['review_id']:r for r in values}
        citation_values = validate_review(read(citation_file),read(citation_path))
        for binding in key:
            rid = binding['review_id']; index = (binding['cell_id'],binding['question_id'])
            if expected.get(rid) != index:raise ValueError('Review key differs from prospective selection')
            if index in opinions:raise ValueError('Duplicate source opinion across completed packs')
            if rid not in citation_values:raise ValueError('Source-first citation opinion is still pending')
            result_path = Path(generation)/binding['cell_id']/'sessions'/binding['question_id']/'result.json'
            if binding['result_sha256'] != sha(result_path):raise ValueError('Review binds another answer')
            opinions[index] = by_id[rid]; citations[index] = citation_values[rid]
            provenance[index] = dict(answer_verdict_sha256=sha(answer_file),citation_verdict_sha256=sha(citation_file),
                result_sha256=sha(result_path),reference_row_sha256=digest(by_id[rid]))
    return opinions, citations, provenance


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='operation',required=True)
    for name in ('select','pack'):
        cmd = sub.add_parser(name)
        for field in ('plan','output'):cmd.add_argument('--'+field,type=Path,required=True)
        if name == 'pack':
            for field in ('selection','resources','generation','dataset'):cmd.add_argument('--'+field,type=Path,required=True)
            cmd.add_argument('--exclude-packs',type=Path);cmd.add_argument('--limit',type=int,default=32)
    args = parser.parse_args()
    if args.output.exists():raise FileExistsError('New immutable source-review pack required')
    plan = read(args.plan);validate(plan);plan_sha = sha(args.plan)
    if args.operation == 'select':
        selection = dict(schema='complete_knowledge_qa_review_selection_v4',plan_sha256=plan_sha,
            policy_sha256=digest(plan['independent_review']),cases=[dict(review_id=secrets.token_hex(16),cell_id=cell,question_id=qid)
            for cell,qid in selected_cases(plan)])
        verify_selection(selection,plan,plan_sha)
        save(args.output/'evaluation_only/selection-and-key.json',selection)
        save(args.output/'receipt.json',dict(plan_sha256=plan_sha,selection_sha256=sha(args.output/'evaluation_only/selection-and-key.json'),
            planned_cases=len(selection['cases']),model_calls=0,answers_read=0,automatic_scores_read=0,human_truth=False))
        print(dict(planned_cases=len(selection['cases']),answers_read=0));return
    verify_dataset(args.dataset,plan['dataset_seal_sha256'])
    selection = verify_selection(read(args.selection),plan,plan_sha)
    if args.limit < 1:raise ValueError('Positive review batch size required')
    excluded = set()
    if args.exclude_packs:
        for key in args.exclude_packs.glob('pack_*/evaluation_only/blind-key.json'):
            excluded.update(r['review_id'] for r in read(key))
    from chapter2_answer_scoring import scoring_payload
    from principia_core.retrieval.knowledge_qa import FrozenKnowledgeCorpus
    resources = read(args.resources)
    if sha(Path(resources['corpus_manifest'])) != plan['artifacts_sha256']['corpus_manifest']:raise ValueError('Review corpus changed')
    corpus = FrozenKnowledgeCorpus(resources['corpus'],resources['corpus_manifest'])
    annotations = {r['id']:r for r in read(args.dataset/'scoring/annotations.json')}
    evidence = read(args.dataset/'scoring/evidence.json')
    questions = {r['id']:r for r in read(args.dataset/'model/questions.json')}
    cells = {r['id']:r for r in plan['cells']}
    inputs=[];citation_inputs=[];key=[];pending=[]
    for row in sorted(selection['cases'],key=lambda r:r['review_id']):
        if row['review_id'] in excluded:continue
        path = args.generation/row['cell_id']/'sessions'/row['question_id']/'result.json'
        if not path.exists():pending.append(row['review_id']);continue
        diagnostic = cells[row['cell_id']]['kind']=='complete_material'
        protocol_path = args.generation/('diagnostic-protocol.json' if diagnostic else 'protocol.json')
        if read(protocol_path)['plan_sha256'] != plan_sha:raise ValueError('Generation belongs to another plan')
        result = verify_result(path,questions[row['question_id']],row['cell_id'],sha(protocol_path))
        payload=None
        if result['status']=='answered':
            delivered=[line for event in result.get('tool_events',[]) for line in event.get('delivered_original_lines',[])]
            payload=scoring_payload(result['question']['question'],annotations[row['question_id']],evidence,corpus,result['answer'],delivered)
        inputs.append(masked_item(row['review_id'],result,payload))
        citation_inputs.append(masked_case(row['review_id'],result['question']['question'],result,corpus))
        key.append(dict(**row,result_sha256=sha(path)))
        if len(inputs)==args.limit:break
    if not inputs:raise ValueError('No available unpacked cases')
    save(args.output/'evaluation_only/answer-inputs.json',inputs)
    save(args.output/'evaluation_only/citation-inputs.json',citation_inputs)
    save(args.output/'evaluation_only/blind-key.json',key)
    save(args.output/'pack-receipt.json',dict(schema='complete_knowledge_qa_masked_pack_v4',plan_sha256=plan_sha,
        created_utc=datetime.now(timezone.utc).isoformat(),selection_sha256=sha(args.selection),
        planned_cases=len(selection['cases']),available_cases=len(inputs),excluded_already_packed=len(excluded),
        answer_inputs_sha256=sha(args.output/'evaluation_only/answer-inputs.json'),
        citation_inputs_sha256=sha(args.output/'evaluation_only/citation-inputs.json'),
        blind_key_sha256=sha(args.output/'evaluation_only/blind-key.json'),automatic_scores_read=0,model_calls=0,
        review_completed=False,human_truth=False,method_model_rank_labels_masked=True,
        limitations=['The host reviewer has project memory; answer wording may reveal clues. AI review is not independent human truth.',
            'Citation inputs exclude gold points; inspect citation originals before opening answer-rubric inputs.']))
    print(dict(cases=len(inputs),pending_unavailable=len(pending),model_calls=0))


if __name__=='__main__':main()
