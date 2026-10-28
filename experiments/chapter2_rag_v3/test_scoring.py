"""Current scoring tests. Synthetic labels are never imported as Human evidence."""
import copy
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import scoring
from judge_contract import VERSION, LEVELS, validate, schema, calculate, metrics
from judge_api_adapter import parse
from judge_statistics import ordinal_agreement,dual_eas,metric_error


class ScoringTests(unittest.TestCase):
    def setUp(self):
        self.packet=scoring.load();self.item=self.packet['items'][0]

    def record(self,judge='gpt_sol'):
        return dict(schema_version=VERSION,sample_id=self.item['sample_id'],judge_id=judge,judge_version=VERSION,status='complete',
            points=[dict(criterion_id=c['criterion_id'],score=.75) for c in self.item['criteria']],fact_gate=.25,
            applicability_gate=.5 if self.item['conditional'] else 'not_applicable')

    def test_levels_schema(self):
        import jsonschema
        for v in LEVELS+['unknown']:
            r=self.record();r['points'][0]['score']=v;r['fact_gate']=v
            validate(r,'joint');jsonschema.validate(r,schema())
        for v in [True,None,.1,float('nan'),2,'0.5']:
            r=self.record();r['fact_gate']=v
            with self.assertRaises(ValueError):validate(r)

    def test_conditional_and_nonconditional(self):
        c=calculate([.25,.75],.75,1,True)
        self.assertAlmostEqual(c['EAS_arith'],75)
        self.assertAlmostEqual(c['EAS_geo'],100*(.5*.75)**(1/3))
        n=calculate([.25,.75],.75,'not_applicable',False)
        self.assertEqual(n['EAS_arith'],62.5);self.assertAlmostEqual(n['EAS_geo'],100*math.sqrt(.5*.75))

    def test_no_gold_weights(self):
        r=self.record();r['points'][0]['score']=0
        cov={k:v for k,v in r.items() if k not in ('fact_gate','applicability_gate')}
        ev={k:v for k,v in r.items() if k!='points'}
        ids=[p['criterion_id'] for p in cov['points']]
        a=metrics(cov,ev,{k:1 for k in ids},self.item['conditional'])
        b=metrics(cov,ev,{k:100 if n==0 else 1 for n,k in enumerate(ids)},self.item['conditional'])
        self.assertEqual(a,b)

    def test_partial_fact_no_hard_gate(self):
        m=calculate([1],.25,'not_applicable',False)
        self.assertEqual(m['EAS_arith'],62.5);self.assertEqual(m['EAS_geo'],50)

    def test_zero_geo_no_smoothing(self):
        m=calculate([1],0,1,True)
        self.assertAlmostEqual(m['EAS_arith'],200/3);self.assertEqual(m['EAS_geo'],0)

    def test_unknown_and_missing_keep_denominator(self):
        m=calculate([1,'unknown'],.5,None,True)
        self.assertIsNone(m['EAS_arith']);self.assertIsNone(m['EAS_geo'])
        self.assertEqual(m['eas_arith_bounds'],[100/3,250/3])
        self.assertEqual(m['eas_geo_bounds'],[0,100*(.5)**(1/3)])
        self.assertEqual((m['unknown_items'],m['missing_items']),(1,1))

    def test_unknown_with_zero_is_still_unknown_point(self):
        m=calculate([0],'unknown','not_applicable',False)
        self.assertIsNone(m['EAS_geo']);self.assertEqual(m['eas_geo_bounds'],[0,0])

    def test_strict_and_failed(self):
        self.assertEqual(calculate([1,1],1,1,True)['Strict'],1)
        self.assertEqual(calculate([1,.75],1,1,True)['Strict'],0)
        self.assertEqual(calculate([1],0,'unknown',True)['Strict'],0)
        self.assertIsNone(calculate([1],1,'unknown',True)['Strict'])
        m=calculate([None],None,None,True,True)
        self.assertEqual((m['EAS_arith'],m['EAS_geo'],m['Strict']),(0,0,0))

    def test_na_validation_and_missing_point(self):
        for cond,a in [(True,'not_applicable'),(False,1)]:
            with self.assertRaises(ValueError):calculate([1],1,a,cond)
        r=self.record();r['points'].pop()
        with self.assertRaises(ValueError):validate(r,'joint',[c['criterion_id'] for c in self.item['criteria']])

    def test_legacy_never_converted(self):
        r=self.record();r['schema_version']='ch2_judge_contract_v1'
        with self.assertRaises(ValueError):validate(r)

    def test_both_request_and_response_protocols(self):
        for j in scoring.JUDGES:
            registry,profile,req=scoring.request_for(j,self.item);r=self.record(j)
            self.assertLessEqual(profile['input_token_cap']+profile['output_token_cap'],32768)
            self.assertNotIn('legacy',json.dumps(req));self.assertNotIn('weights',json.dumps(req))
            raw=dict(model=profile['model_id'],id='synthetic')
            if profile['protocol']=='responses':
                raw.update(status='completed',output=[dict(type='message',role='assistant',content=[dict(type='output_text',text=json.dumps(r))])],usage=dict(input_tokens=100,output_tokens=100))
            else:
                raw.update(choices=[dict(finish_reason='stop',message=dict(content=json.dumps(r)))],usage=dict(prompt_tokens=100,completion_tokens=100))
            self.assertEqual(parse(profile,raw,self.item,'joint')['record'],r)
            raw['model']='wrong'
            with self.assertRaises(ValueError):parse(profile,raw,self.item,'joint')

    def test_parser_rejects_duplicate_and_truncation(self):
        _,p,_=scoring.request_for('deepseek_flash',self.item)
        raw=dict(model=p['model_id'],choices=[dict(finish_reason='stop',message=dict(content='{"x":1,"x":2}'))],usage=dict(prompt_tokens=10,completion_tokens=10))
        with self.assertRaises(ValueError):parse(p,raw,self.item,'joint')
        raw['choices'][0]['finish_reason']='length'
        with self.assertRaises(ValueError):parse(p,raw,self.item,'joint')

    def test_five_level_agreement(self):
        a=ordinal_agreement([(.25,.25),(.75,.5),('unknown',1),(None,0)])
        self.assertEqual(a['n'],2);self.assertEqual(a['unknown_pairs'],2);self.assertEqual(a['exact'],.5)
        self.assertIsNotNone(a['quadratic_kappa'])
        self.assertEqual(a['mae'],.125);self.assertEqual(a['bias_right_minus_left'],-.125)
        self.assertEqual(sum(c['count'] for c in a['confusion']),2)

    def test_constant_human_marginal_does_not_mean_zero_exact_agreement(self):
        a=ordinal_agreement([(1,1)]*3+[(1,.75)]*3)
        self.assertEqual(a['exact'],.5);self.assertEqual(a['quadratic_kappa'],0)
        self.assertEqual(a['mae'],.125);self.assertEqual(a['bias_right_minus_left'],-.125)
        a=ordinal_agreement([('unknown',1),(None,0)])
        self.assertIsNone(a['mae']);self.assertEqual(a['n'],0)

    def test_import_rejects_tampered_binding_without_reading_audit_answers(self):
        bindings=scoring.verify_human_binding(self.packet,dict(drafts={}))
        self.assertEqual(len(bindings),18)
        packet=copy.deepcopy(self.packet);packet['items'][0]['answer']+='tampered'
        with self.assertRaisesRegex(ValueError,'digest mismatch'):scoring.verify_human_binding(packet,dict(drafts={}))
        packet=copy.deepcopy(self.packet);packet['private'][0]['answer_sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'identity mismatch'):scoring.verify_human_binding(packet,dict(drafts={}))
        path=scoring.DEFAULT_RUN/'experiments/agentic/reused_inputs/sampling_plan.answers_sealed_v1.json'
        h=scoring.sha(path);audit=next(s for s in scoring.read(path)['samples'] if s['batch']=='audit')
        sid='S'+scoring.hashlib.sha256((h+'|'+audit['sample_key']).encode()).hexdigest()[:16]
        with self.assertRaisesRegex(ValueError,'Sealed audit IDs'):scoring.verify_human_binding(self.packet,dict(drafts={sid:{}}))

    def test_summary_unknown_not_dropped(self):
        known=calculate([1],1,'not_applicable',False);missing=calculate([None],None,'not_applicable',False)
        s=scoring.summarize([known,missing])
        self.assertIsNone(s['EAS_arith']);self.assertIsNone(s['EAS_geo'])
        self.assertEqual(s['eas_arith_bounds'],[50,100]);self.assertEqual(s['expected_answers'],2)

    def test_calibration_only_and_independent(self):
        self.assertEqual(len(self.packet['items']),18)
        self.assertFalse(self.packet['audit_included']);self.assertFalse(self.packet['test160_included'])
        self.assertEqual({s['batch'] for s in self.packet['private']},{'calibration'})
        for item in self.packet['items']:
            self.assertNotIn('legacy',item);self.assertNotIn('method_id',item);self.assertNotIn('generator_id',item)

    def test_browser_python_dual_metric_parity(self):
        folder=scoring.ROOT/'verification/browser'
        exported=scoring.read(folder/'synthetic_complete.json');browser=scoring.read(folder/'synthetic_metrics.json')
        byid={m['sample_id']:m for m in browser}
        for i in self.packet['items']:
            d=exported['drafts'][i['sample_id']];v=d['values']
            m=calculate([v[c['criterion_id']] for c in i['criteria']],v['F'],v['A'] if i['conditional'] else 'not_applicable',i['conditional'],i['generation_failed'])
            for key in ('EAS_arith','EAS_geo','Strict'):
                self.assertAlmostEqual(m[key],byid[i['sample_id']][key])
            for key in ('eas_arith_bounds','eas_geo_bounds'):
                for x,y in zip(m[key],byid[i['sample_id']][key]):self.assertAlmostEqual(x,y)

    def test_import_complete_partial_and_legacy(self):
        source=scoring.ROOT/'verification/browser'
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with patch.object(scoring,'ROOT',root),patch.object(scoring,'load',return_value=self.packet),patch.object(scoring,'report'),patch('human_unified.build_page'):
                scoring.import_human(source/'synthetic_complete.json')
                self.assertEqual(len(scoring.rows(root/'human/scores.jsonl')),18)
                scoring.import_human(source/'roundtrip.json')
                self.assertEqual(len(scoring.rows(root/'human/scores.jsonl')),1)
                before=(root/'human/scores.jsonl').read_bytes()
                with self.assertRaises(ValueError):scoring.import_human(source/'invalid_import.json')
                self.assertEqual((root/'human/scores.jsonl').read_bytes(),before)
                self.assertEqual(len(list((root/'human/submissions').glob('*.json'))),2)

    def test_total_32k_and_reported_split_overrun(self):
        _,p,_=scoring.request_for('gpt_sol',self.item)
        raw=dict(model=p['model_id'],choices=[dict(finish_reason='stop',message=dict(content=json.dumps(self.record())))],usage=dict(prompt_tokens=3000,completion_tokens=8500))
        parsed=scoring.parse_current(p,raw,self.item)
        self.assertTrue(parsed['budget_observation']['provider_split_cap_exceeded'])
        raw['usage']['prompt_tokens']=32000
        with self.assertRaises(ValueError):scoring.parse_current(p,raw,self.item)

    def test_reuse_checks_current_request_and_raw_response(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);target=root/'requests/gpt_sol'/self.item['sample_id']/'attempt_1'
            target.mkdir(parents=True)
            # Generate an isolated fixture from the current contract; historical
            # calibration requests preserve older transport shapes by design.
            _,profile,current=scoring.request_for('gpt_sol',self.item)
            raw=dict(model=profile['model_id'],choices=[dict(finish_reason='stop',message=dict(content=json.dumps(self.record())))],
                     usage=dict(prompt_tokens=100,completion_tokens=100))
            scoring.write(target/'request.json',dict(request=current,fingerprint=scoring.fingerprint()))
            scoring.write(target/'response.txt',raw)
            scoring.write(target/'parsed.json',scoring.parse_current(profile,raw,self.item))
            original_parsed=(target/'parsed.json').read_bytes()
            with patch.object(scoring,'ROOT',root):
                self.assertEqual(len(scoring.collect('gpt_sol',[self.item])),1)
                parsed=scoring.read(target/'parsed.json');parsed['record']['fact_gate']='unknown'
                scoring.write(target/'parsed.json',parsed)
                with self.assertRaisesRegex(ValueError,'differs from raw response'):scoring.collect('gpt_sol',[self.item])
                (target/'parsed.json').write_bytes(original_parsed)
                request=scoring.read(target/'request.json');request['request']['url']+='tampered'
                scoring.write(target/'request.json',request)
                with self.assertRaisesRegex(ValueError,'differs from current protocol'):scoring.collect('gpt_sol',[self.item])

    def test_partial_human_draft_narrows_bounds_without_adopting_old_values(self):
        item=dict(self.item,conditional=False,criteria=[dict(criterion_id='K001'),dict(criterion_id='K002')])
        draft=dict(values={'K001':1,'K002':.75,'F':.25},confirmed={'K001':True,'K002':False,'F':True})
        m=scoring.draft_metrics(item,draft)
        self.assertIsNone(m['EAS_arith']);self.assertIsNone(m['EAS_geo'])
        self.assertEqual(m['eas_arith_bounds'],[37.5,62.5])
        self.assertAlmostEqual(m['eas_geo_bounds'][0],100*math.sqrt(.5*.25))
        self.assertEqual(m['missing_items'],1)

    def test_dual_mae_averages_per_answer_before_absolute_error(self):
        def metric(v):return dict(EAS_arith=v,EAS_geo=v,eas_arith_bounds=[v,v],eas_geo_bounds=[v,v])
        both=dual_eas([metric(40),metric(60)])
        self.assertEqual(metric_error([('q',both['EAS_arith']-50)])['mae'],0)
        self.assertEqual((abs(40-50)+abs(60-50))/2,10)
        missing=metric(None);missing.update(eas_arith_bounds=[0,100],eas_geo_bounds=[0,100])
        result=dual_eas([metric(40),missing])
        self.assertIsNone(result['EAS_arith']);self.assertEqual(result['eas_arith_bounds'],[20,70])
        with self.assertRaises(ValueError):dual_eas([metric(40)])

    def test_review_contains_only_three_calibration_questions_and_current_human(self):
        import scoring_review as review
        packet=review.review_packet()
        self.assertEqual({g['question_id'] for g in packet['groups']},set(review.QUESTIONS))
        self.assertEqual(sum(len(g['answers']) for g in packet['groups']),9)
        for group in packet['groups']:
            self.assertIn('critical_errors',group['gold']);self.assertTrue(group['sources'])
            for answer in group['answers']:self.assertEqual(answer['human']['judge_id'],'human')

    def test_audit_guard_rejects_unapproved_or_drifted_protocol(self):
        import scoring_review as review
        p=copy.deepcopy(review.protocol())
        with tempfile.TemporaryDirectory() as tmp,patch.object(review,'ROOT',Path(tmp)):
            p['status']='candidate_pending_professional_confirmation'
            scoring.write(Path(tmp)/'protocol.json',p)
            with self.assertRaises(PermissionError):review.guard_audit(require_packet=False)
            p.update(status='preaudit_frozen');p['acceptance']['status']='owner_approved_before_audit'
            p['freeze']=dict(protocol_definition_sha256=review.digest(review.definition(p)),source_sha256=review.frozen_sources())
            p['freeze']['freeze_id']=review.digest(p['freeze'])
            scoring.write(Path(tmp)/'protocol.json',p)
            review.guard_audit(require_packet=False)
            p['statistics']['bias']='wrong direction';scoring.write(Path(tmp)/'protocol.json',p)
            with self.assertRaisesRegex(ValueError,'statistics/review'):review.guard_audit(require_packet=False)

    def test_review_clarification_cannot_release_audit(self):
        import scoring_review as review
        packet=review.review_packet()
        data=dict(schema_version=VERSION,review_id=packet['review_id'],decisions={k:dict(decision='confirm') for k in list(review.QUESTIONS)+['acceptance']})
        data['decisions']['acceptance']['decision']='needs_clarification'
        with tempfile.TemporaryDirectory() as tmp,patch.object(review,'ROOT',Path(tmp)):
            root=Path(tmp);scoring.write(root/'review_packet.json',packet)
            (root/'human_five_level.json').write_bytes((scoring.ROOT/'human_five_level.json').read_bytes())
            scoring.write(root/'answer.json',data)
            result=review.import_review(root/'answer.json')
            self.assertFalse(result['confirmed']);self.assertFalse((root/'audit/packet.json').exists())

    def test_audit_gates_both_judges_and_both_metrics(self):
        import scoring_review as review
        criteria=review.protocol()['acceptance'];items=[dict(sample_id='T'+str(n),conditional=False) for n in range(12)]
        labels={j:{i['sample_id']:dict(fact_gate=1,applicability_gate='not_applicable') for i in items} for j in ('human',)+scoring.JUDGES}
        errors={key:dict(identified_pairs=12,mae=0,bias_right_minus_left=0) for key in ('EAS_arith','EAS_geo')}
        s=dict(records=[],agreement={j:dict(K=dict(exact=1,quadratic_kappa=1),**copy.deepcopy(errors)) for j in scoring.JUDGES},dual_mean_vs_human=copy.deepcopy(errors))
        self.assertTrue(review.evaluate_audit(s,criteria,labels,items)['accepted'])
        changed=copy.deepcopy(s);changed['dual_mean_vs_human']['EAS_geo']['mae']=6
        self.assertIn('dual_mean:EAS_geo:MAE',review.evaluate_audit(changed,criteria,labels,items)['failed_gates'])
        changed=copy.deepcopy(s);changed['agreement']['gpt_sol']['K']['quadratic_kappa']=None
        self.assertEqual(review.evaluate_audit(changed,criteria,labels,items)['decision'],'manual_review')
        labels['human']['T0']['fact_gate']=0
        self.assertEqual(review.evaluate_audit(s,criteria,labels,items)['decision'],'manual_review')

    def test_blind_audit_page_starts_without_scores_or_old_references(self):
        from human_unified import build_page
        item=copy.deepcopy(self.item);item['sample_id']='SYNTHETIC_AUDIT_ONLY'
        prepared=dict(schema_version=VERSION,batch='audit',packet_id='synthetic_only',items=[item],
            ui=[dict(sample_id=item['sample_id'],group_id='A01',label='answer',legacy=None)])
        with tempfile.TemporaryDirectory() as tmp,patch.object(scoring,'ROOT',Path(tmp)):
            path=build_page(prepared);html=path.read_text(encoding='utf-8')
            self.assertEqual(path.name,'index.html');self.assertEqual(path.parent,Path(tmp))
            self.assertIn('"human_blind": true',html);self.assertIn('"saved": null',html)
            self.assertNotIn('"judge_id"',html);self.assertNotIn('"private"',html)

    def test_released_audit_import_12_only_in_temporary_directory(self):
        import scoring_review as review
        path=review.ROOT/'audit/packet.json'
        if not path.exists():self.skipTest('Audit still sealed')
        packet=scoring.read(path)
        data=dict(schema_version=VERSION,packet_id=packet['packet_id'],drafts={})
        for item in packet['items']:
            fields=[c['criterion_id'] for c in item['criteria']]+['F']+(['A'] if item['conditional'] else [])
            data['drafts'][item['sample_id']]=dict(values={k:.5 for k in fields},confirmed={k:True for k in fields},reason='synthetic temporary test only')
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);file=root/'synthetic.json';scoring.write(file,data)
            with patch.object(scoring,'ROOT',root),patch.object(scoring,'load',return_value=packet),patch.object(scoring,'report'),patch('human_unified.build_page'):
                scoring.import_human(file)
                self.assertEqual(len(scoring.rows(root/'human/scores.jsonl')),12)
                validation=scoring.read(root/'human/import_validation.json')
                self.assertEqual(validation['audit_records_found'],12)
                # A Dev submission cannot enter the audit reference, even with a complete set.
                data['packet_id']=self.packet['packet_id'];scoring.write(file,data)
                with self.assertRaises(ValueError):scoring.import_human(file)

    def test_dev_shortlist_retains_methods_and_models_without_full_grid(self):
        import dev40_optimization as dev
        with tempfile.TemporaryDirectory() as tmp,patch.object(dev,'ROOT',Path(tmp)):
            source=scoring.DEFAULT_RUN/'experiments/agentic/dev40/candidate_matrix.json'
            (Path(tmp)/'candidate_matrix.json').write_bytes(source.read_bytes())
            current=dev.shortlist()
            self.assertEqual(current['active_configurations'],26)
            self.assertEqual(current['deferred_configurations'],48)
            self.assertEqual(current['baseline_sessions'],1040)
            self.assertEqual(current['api_calls'],0)
            self.assertEqual(dev.shortlist(),current)

    def test_final_dev_selection_rejects_failed_audit(self):
        import dev40_optimization as dev
        with patch('scoring_review.guard_audit',return_value=dict(status='audit_complete',reliability_accepted=False)),patch('dev40_scoring.guard_operational',side_effect=PermissionError('No owner authorization')):
            with self.assertRaisesRegex(PermissionError,'audit has not passed'):dev.select(Path('unused.json'),Path('unused-output.json'))

    def test_dev_report_does_not_replace_pending_or_ungraded_answers_with_scores(self):
        import dev40_optimization as dev
        import dev40_report as report
        with tempfile.TemporaryDirectory() as tmp,patch.object(dev,'ROOT',Path(tmp)/'dev40'),patch.object(report,'DEFAULT_RUN',Path(tmp)):
            root=dev.ROOT;root.mkdir()
            source=scoring.DEFAULT_RUN/'experiments/agentic/dev40'
            for name in ('candidate_matrix.json','shortlist.json'):(root/name).write_bytes((source/name).read_bytes())
            configs=scoring.read(root/'candidate_matrix.json')['configurations']
            c=next(c for c in configs if c['model_key']=='qwen3_14b' and c['method_id']=='direct')
            q=scoring.read(dev.QUESTIONS)[0]
            scoring.write(root/'generation'/c['config_id']/q['id']/'result.json',dict(status='http_rejected'))
            output=report.report()
            group=next(g for g in output['candidates'] if g['config_id']==c['config_id'])
            self.assertEqual(group['failed'],1);self.assertEqual(group['pending'],39)
            self.assertIsNone(group['EAS_arith']);self.assertEqual(group['EAS_arith_bounds'],[0,97.5])
            self.assertFalse(output['parameters_frozen']);self.assertFalse(output['test160']['ready'])


if __name__=='__main__':unittest.main()
