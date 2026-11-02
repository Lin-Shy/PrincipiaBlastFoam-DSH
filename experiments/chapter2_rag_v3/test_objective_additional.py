"""Additional edge checks for frozen objective scoring and inference."""
import unittest
from objective_scoring import score
from objective_statistics import analyze

class ObjectiveEdgeTests(unittest.TestCase):
    def test_tolerance_boundaries_and_required_unit_policy(self):
        q={'id':'Q','type':'fill'}
        g={'answer':'10','numeric':True,'absolute_tolerance':'0.5'}
        def grade(value):
            return score(q,g,{'status':'answered','answer':'FINAL: '+value})
        self.assertEqual(grade('9.5')['score'],1)
        self.assertEqual(grade('10.5')['score'],1)
        self.assertEqual(grade('10.500001')['score'],0)
        self.assertFalse(grade('10 Pa')['format_valid'])
    def test_empty_and_missing_answer(self):
        q={'id':'Q','type':'fill'}; g={'answer':'a'}
        for answer in ('','FINAL:','FINAL:   '):
            self.assertEqual(score(q,g,{'status':'answered','answer':answer})['score'],0)
    def test_complete_26_configurations_cluster_inference(self):
        methods=['graph','bm25','e5','bge','hybrid1','hybrid2','parent','basic','direct',
                 'no_cross','no_aliases','no_traversal','anchor_only']
        rows=[]
        for model in ('8b','14b'):
            for method in methods:
                for i in range(4):
                    rows.append(dict(config_id=model+'_'+method,model=model,method=method,
                                     cluster=str(i//2),score=int(method=='graph' or i%2==0)))
        protocol={'seed':20261102,'bootstrap_samples':10000,'families':{'main':16,'ablation':8}}
        first=analyze(rows,protocol); second=analyze(rows,protocol)
        self.assertEqual(first,second)
        self.assertEqual(len(first['ci95']),26)
        self.assertEqual(len(first['paired']),24)
        self.assertEqual([sum(x['family']==f for x in first['paired']) for f in ('main','ablation')],[16,8])
        self.assertTrue(all(0<=x['holm_p']<=1 for x in first['paired']))

if __name__=='__main__':unittest.main()
