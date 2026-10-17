"""New complete-matrix analysis using the unchanged linked-group statistics."""
import argparse
from collections import Counter,defaultdict
from pathlib import Path

from chapter2_v2_retrieval_probe import read,save,sha
from chapter2_full_protocol import validate,verify_dataset,verify_result
from chapter2_full_review import verify_selection,load_reviews
from chapter2_knowledge_formal_review import sensitivity_bounds
from chapter2_knowledge_evaluation import primary_bounds,evidence_coverage
from chapter2_qa_statistics import aggregate_planned,paired_comparison,holm_planned
from chapter2_analyze_knowledge_formal import completion_gate,final_conclusions
from chapter2_full_costs import physical_cost


def series_specs(plan):
    validate(plan);specs=defaultdict(list)
    for cell in plan['cells']:specs[cell['id'].rsplit('/',1)[0]].append(cell)
    for group in specs.values():
        if sorted(c['repeat'] for c in group)!=[1,2,3] or any(c['question_ids']!=group[0]['question_ids'] for c in group):
            raise ValueError('Complete matched repeats required')
    return dict(specs)


def aggregate(rows,annotations,ids):
    return aggregate_planned([r for r in rows if r['question_id'] in set(ids)],annotations,ids,3)


def compare(plan,annotations,rows):
    specs=series_specs(plan)
    def find(kind,model,method,variant=None):
        matches=[name for name,cs in specs.items() if cs[0]['kind']==kind and cs[0]['model']==model and cs[0]['method']==method
            and (variant is None or cs[0]['graph_ablation']==variant)]
        if len(matches)!=1:raise ValueError('Unique registered comparison required')
        return matches[0]
    def pair(left,right,ids):
        value=paired_comparison(aggregate(rows[left],annotations,ids),aggregate(rows[right],annotations,ids),
            resamples=plan['statistics']['bootstrap_resamples'],seed=plan['statistics']['seed'])
        return dict(**value,left_series=left,right_series=right,planned_questions=len(ids),planned_observations_per_side=len(ids)*3)
    primary={};mechanism={};supplements={};model_size={}
    for item in plan['primary_comparison_family']:
        primary[item['model']+':graph-'+item['right']]=pair(find('main',item['model'],'graph'),find('main',item['model'],item['right']),plan['test_ids'])
    for item in plan['mechanism_comparison_family']:
        mechanism[item['model']+':full-'+item['right']]=pair(find('main',item['model'],'graph'),find('ablation',item['model'],'graph',item['right']),plan['test_ids'])
    for name,cs in specs.items():
        c=cs[0]
        if c['kind'] in {'knowledge_budget','decision_budget'}:
            supplements[name]=pair(name,find('main',c['model'],c['method']),c['question_ids'])
        elif c['kind']=='complete_material':
            for method in ('bm25','e5','hybrid','graph','none'):
                supplements[name+'-'+method]=pair(name,find('main',c['model'],method),c['question_ids'])
    for method in ('bm25','e5','hybrid','graph','none'):
        model_size[method]=pair(find('main','qwen3-14b',method),find('main','qwen3-8b',method),plan['test_ids'])
    for value in [*supplements.values(),*model_size.values()]:
        value['significance_claim_allowed']=False
        value['interpretation']='Descriptive same-question same-repeat comparison; outside primary and mechanism families.'
    return dict(primary=primary,primary_holm=holm_planned(primary),mechanism=mechanism,
        mechanism_holm=holm_planned(mechanism),supplements=supplements,model_size=model_size)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('plan','dataset','generation','scores','selection','reviews','output'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():raise FileExistsError('New immutable analysis required')
    plan=read(args.plan);validate(plan);plan_sha=sha(args.plan);verify_dataset(args.dataset,plan['dataset_seal_sha256'])
    selection=verify_selection(read(args.selection),plan,plan_sha)
    review,citations,provenance=load_reviews(args.reviews,plan,plan_sha,args.generation,args.selection)
    selected={(r['cell_id'],r['question_id']) for r in selection['cases']}
    annotations={r['id']:r for r in read(args.dataset/'scoring/annotations.json')}
    questions={r['id']:r for r in read(args.dataset/'model/questions.json')};evidence=read(args.dataset/'scoring/evidence.json')
    specs=series_specs(plan);rows=[];series_rows=defaultdict(list);fixed=defaultdict(list);sensitivity=defaultdict(list)
    delivered=defaultdict(list);coverage=defaultdict(list);factual=defaultdict(list);conditional=defaultdict(list)
    citation_rows=defaultdict(list);costs={};bindings={};trajectories=[];disagreements=0
    score_protocol=args.scores/'protocol.json';score_protocol_sha=sha(score_protocol) if score_protocol.exists() else None
    if score_protocol.exists() and read(score_protocol)['plan_sha256']!=plan_sha:raise ValueError('Scores belong to another activity')
    for cell in plan['cells']:
        name=cell['id'].rsplit('/',1)[0];rep=cell['repeat']-1;generation_requests=[];grade_requests=[]
        gprotocol=args.generation/('diagnostic-protocol.json' if cell['kind']=='complete_material' else 'protocol.json')
        gsha=sha(gprotocol) if gprotocol.exists() else None
        if gprotocol.exists() and read(gprotocol)['plan_sha256']!=plan_sha:raise ValueError('Generation belongs to another activity')
        for qid in cell['question_ids']:
            index=(cell['id'],qid);folder=args.generation/cell['id']/'sessions'/qid;rp=folder/'result.json'
            sp=args.scores/cell['id']/'sessions'/qid/'score.json';result=score=None;ev=None
            if rp.exists():
                result=verify_result(rp,questions[qid],cell['id'],gsha);bindings[str(rp)]=sha(rp)
                generation_requests.extend((folder/'requests').glob('*.json'))
                ev=evidence_coverage(result,annotations[qid],evidence)
            if sp.exists():
                if not result or score_protocol_sha is None:raise ValueError('Score without bound generation')
                score=read(sp)
                expected=dict(formal_result=True,formal_cell_id=cell['id'],question_id=qid,result_sha256=sha(rp),
                    generation_status=result['status'],protocol_sha256=score_protocol_sha,reference_provenance=provenance.get(index))
                if any(score.get(k)!=v for k,v in expected.items()) or read(sp.parent/'score-binding.json')!=dict(
                    score_sha256=sha(sp),result_sha256=sha(rp),protocol_sha256=score_protocol_sha):raise ValueError('Score integrity changed')
                if index in selected and index not in review:raise ValueError('Selected score lacks source-first opinion')
                bindings[str(sp)]=sha(sp);grade_requests.extend((sp.parent/'requests').glob('*.json'))
            lo,hi=primary_bounds(score);value=score['metrics']['complete_valid_answer'] if score else None
            independent=review.get(index,{}).get('complete_valid_answer');reviewed=sensitivity_bounds(value,independent,index in selected)
            if value is not None and independent is not None and value!=independent:disagreements+=1
            observed=dict(question_id=qid,replicate=rep)
            fixed[name].append(dict(**observed,lower=lo,upper=hi));sensitivity[name].append(dict(**observed,lower=reviewed[0],upper=reviewed[1]))
            if ev is not None:delivered[name].append(dict(**observed,lower=ev['complete_necessary_evidence'],upper=ev['complete_necessary_evidence']))
            m=score.get('metrics',{}) if score else {};failed=result is not None and result['status']!='answered'
            cb=(0,0) if failed else (m.get('required_point_coverage_lower',0),m.get('required_point_coverage_upper',1))
            coverage[name].append(dict(**observed,lower=cb[0],upper=cb[1]))
            fb=(0,0) if failed else (int(m.get('factuality')=='pass'),int(m.get('factuality')!='fail'))
            factual[name].append(dict(**observed,lower=fb[0],upper=fb[1]))
            if annotations[qid]['labels']['condition_discrimination']:
                ab=(0,0) if failed else (int(m.get('applicability')=='pass'),int(m.get('applicability')!='fail'))
                conditional[name].append(dict(**observed,lower=ab[0],upper=ab[1]))
            if index in selected:
                cm=citations.get(index,{})
                citation_rows[name].append(dict(**observed,lower=cm.get('complete_lower',0),upper=cm.get('complete_upper',1)))
                if result:
                    trajectories.append(dict(cell_id=cell['id'],question_id=qid,result_file=str(rp),result_sha256=sha(rp),
                        turn_actions=[dict(turn=t['turn'],action=t.get('action'),response_status=t.get('response',{}).get('status')) for t in result.get('turns',[])],
                        evidence=ev,references=result.get('references'),source_opinion=review.get(index),citation_metrics=citations.get(index)))
            row=dict(cell_id=cell['id'],series=name,question_id=qid,replicate=rep,group=annotations[qid]['split_group'],
                generation_status=result['status'] if result else 'unattempted',judge_status=score['status'] if score else 'pending',
                score_record_present=score is not None,fixed_primary_bounds=[lo,hi],reviewed_primary_bounds=list(reviewed),
                independent_primary=independent,review_selected=index in selected,evidence=ev,auxiliary_metrics=m,
                tool_calls=result.get('tool_calls',len(result.get('tool_events',[]))) if result else None,seconds=result.get('seconds') if result else None,
                knowledge_characters=result.get('knowledge_characters') if result else None)
            rows.append(row);series_rows[name].append(row)
        costs[cell['id']]=dict(generation=physical_cost(generation_requests),judge=physical_cost(grade_requests))
    summaries={}
    for name,cs in specs.items():
        ids=cs[0]['question_ids'];condition_ids=[q for q in ids if annotations[q]['labels']['condition_discrimination']]
        citation_ids=[q for q in ids if q in plan['diagnostic_ids']]
        strata={}
        for integration in ('single','multiple'):
            for flag in (False,True):
                subset=[q for q in ids if annotations[q]['labels']['evidence_integration']==integration and annotations[q]['labels']['condition_discrimination'] is flag]
                if subset:strata[integration+':'+str(flag)]=dict(fixed=aggregate(fixed[name],annotations,subset),reviewed_sensitivity=aggregate(sensitivity[name],annotations,subset))
        summaries[name]=dict(fixed=aggregate(fixed[name],annotations,ids),reviewed_sensitivity=aggregate(sensitivity[name],annotations,ids),
            delivered_complete_evidence=aggregate(delivered[name],annotations,ids),required_point_coverage=aggregate(coverage[name],annotations,ids),
            end_to_end_factual_acceptability=aggregate(factual[name],annotations,ids),
            conditional_answer_acceptability=aggregate(conditional[name],annotations,condition_ids) if condition_ids else None,
            preselected_citation_support=aggregate(citation_rows[name],annotations,citation_ids) if citation_ids else None,
            generation_status=dict(Counter(r['generation_status'] for r in series_rows[name])),
            judge_status=dict(Counter(r['judge_status'] for r in series_rows[name])),strata=strata)
    fixed_comparisons=compare(plan,annotations,fixed);reviewed_comparisons=compare(plan,annotations,sensitivity)
    gate=completion_gate(plan,rows,review,selected)
    gate['pending_citation_opinions']=len(selected-set(citations));gate['whole_registered_scope_complete'] &= not gate['pending_citation_opinions']
    save(args.output/'observations.json',rows);save(args.output/'prospective_trajectory_index.json',trajectories);save(args.output/'physical-costs.json',costs)
    report=dict(schema='complete_knowledge_qa_analysis_v4',formal_result=True,plan_sha256=plan_sha,
        planned_sessions=len(rows),generation_results=sum(r['generation_status']!='unattempted' for r in rows),
        completed_scores=sum(r['score_record_present'] for r in rows),planned_independent_reviews=len(selected),
        completed_independent_reviews=len(review),completed_citation_opinions=len(citations),independent_review_disagreements=disagreements,
        series=summaries,fixed_comparisons=fixed_comparisons,reviewed_comparisons=reviewed_comparisons,
        completion_gate=gate,conclusions=final_conclusions(fixed_comparisons,reviewed_comparisons,gate),human_truth=False,
        observations_sha256=sha(args.output/'observations.json'),trajectory_index_sha256=sha(args.output/'prospective_trajectory_index.json'),
        physical_costs_sha256=sha(args.output/'physical-costs.json'),input_file_bindings=bindings,
        limits=['Historically exposed test set; not fresh unseen confirmation. Development and test results remain separate.',
            'Unknown identification bounds differ from group-bootstrap uncertainty. Group weak dependence and sign exchangeability remain assumptions.',
            'Original AI judge and host source/citation opinions are not independent human truth.',
            'Auxiliary coverage, factuality, applicability, source delivery, citations and strict whole-answer success are distinct.',
            'Physical costs retain failures and missing usage. Host AI, hardware, electricity and inherited construction are not measured.'])
    save(args.output/'report.json',report)
    print(dict(planned=len(rows),generation=report['generation_results'],scores=report['completed_scores'],completion=gate))


if __name__=='__main__':main()
