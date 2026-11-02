import tempfile
import unittest
from pathlib import Path
import objective_statistics_audit as audit
import objective_experiment as exp

class StatisticsAuditTests(unittest.TestCase):
    def test_csv_round_trip_and_tampering(self):
        rows=[{'id':'Q1','score':1,'format_valid':True,'raw_answer':'A, B','missing':None}]
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[2]/'.local') as tmp:
            path=Path(tmp)/'rows.csv';exp.export_csv(path,rows)
            audit.check_rows_csv(path,rows)
            path.write_text(path.read_text(encoding='utf-8-sig').replace('True','False'),encoding='utf-8-sig')
            with self.assertRaises(ValueError):audit.check_rows_csv(path,rows)
if __name__=='__main__':unittest.main()
