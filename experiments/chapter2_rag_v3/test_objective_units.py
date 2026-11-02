"""Unit-aware extension tests; frozen results remain unchanged without unit metadata."""
import unittest
from objective_scoring import score as frozen_score
from objective_scoring_units import score, numeric_with_units

class UnitScoringTests(unittest.TestCase):
    def setUp(self):
        self.q={'id':'fixture','type':'short'}
        self.g={'answer':'1','numeric':True,'answer_unit':'kPa','absolute_tolerance':'0.001'}
    def grade(self,text):return score(self.q,self.g,{'status':'answered','answer':text})
    def test_unit_conversion_exact_and_scientific(self):
        for text in ('FINAL: 1000 Pa','FINAL: 0.001 MPa','FINAL: 1e3 Pa','FINAL: 0.01 bar'):
            with self.subTest(text=text):self.assertEqual(self.grade(text)['score'],1)
    def test_converted_tolerance_boundaries(self):
        for text in ('FINAL: 999 Pa','FINAL: 1001 Pa'):self.assertEqual(self.grade(text)['score'],1)
        for text in ('FINAL: 998.999 Pa','FINAL: 1001.001 Pa'):self.assertEqual(self.grade(text)['score'],0)
    def test_dimension_unknown_missing_and_case(self):
        for text in ('FINAL: 1 m','FINAL: 1','FINAL: 1 KPa','FINAL: 1 foo','FINAL: NaN kPa','FINAL: 1 kPa or 1000 Pa','FINAL: 1e999999999 Pa'):
            with self.subTest(text=text):
                r=self.grade(text);self.assertEqual(r['score'],0);self.assertFalse(r['format_valid'])
    def test_marker_conflict_empty_and_failure(self):
        for text in ('','FINAL:','FINAL: 1 kPa\nFINAL: 1000 Pa','1 kPa'):
            self.assertEqual(self.grade(text)['score'],0)
        self.assertEqual(score(self.q,self.g,{'status':'transport_error','answer':'FINAL: 1 kPa'})['score'],0)
    def test_unit_alias_unicode_and_numeric_sign(self):
        g={'answer':'0.000002','numeric':True,'answer_unit':'s'}
        self.assertEqual(numeric_with_units('2 µs',g)[1],True)
        self.assertEqual(numeric_with_units('-2 μs',g)[1],False)
    def test_bad_metadata_rejected(self):
        for update in ({'answer_unit':'unsupported'},{'absolute_tolerance':'-1'},{'relative_tolerance':'NaN'}):
            with self.subTest(update=update),self.assertRaises(ValueError):numeric_with_units('1 kPa',{**self.g,**update})
    def test_without_unit_metadata_preserves_frozen_scoring(self):
        g={'answer':'1','numeric':True,'absolute_tolerance':0}
        for text in ('FINAL: 1','FINAL: 1 kPa','FINAL: 2','no final','FINAL: 1\nFINAL: 2'):
            result={'status':'answered','answer':text}
            self.assertEqual(score(self.q,g,result),frozen_score(self.q,g,result))

if __name__=='__main__':unittest.main()
