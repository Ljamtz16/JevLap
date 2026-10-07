import unittest
from datetime import datetime,timedelta,timezone
from calibration_analysis import analyze,isotonic_fit,predict


class CalibrationTests(unittest.TestCase):
    def row(self,day,minute=0,pnl=10,confidence=.8):
        ts=day.replace(hour=14,minute=minute)
        return dict(timestamp=ts.isoformat(),exit_timestamp=(ts+timedelta(minutes=15)).isoformat(),
                    symbol='SPY',research_mode='snapshot_shadow',side='CALL',status='CLOSED',pnl=pnl,
                    confidence=confidence,model='jev',config={'threshold':.75},simulation_version='v2',dataset_policy='COMMON')
    def test_one_day_is_insufficient_even_with_many_snapshots(self):
        day=datetime(2026,10,6,tzinfo=timezone.utc)
        rows=[self.row(day,m) for m in range(60)]
        report=analyze(rows,day+timedelta(days=1))
        self.assertEqual(report['status'],'INSUFFICIENT_INDEPENDENT_DAYS')
        self.assertEqual(report['segments'][0]['independent_labels'],1)
        self.assertIsNone(report['segments'][0]['mapping'])
        self.assertEqual(report['trading_threshold'],.75)
    def test_future_exit_missing_outcome_and_models_are_separated(self):
        day=datetime(2026,10,6,tzinfo=timezone.utc);a=self.row(day);b=self.row(day);b['model']='different'
        future=self.row(day+timedelta(days=2));missing=dict(a,status='INCOMPLETE',pnl=None)
        report=analyze([a,b,future,missing],day+timedelta(days=1))
        self.assertEqual(len(report['segments']),2)
        self.assertEqual(report['exclusions']['FUTURE_DECISION'],1)
        self.assertTrue(report['provider_probabilities_unchanged']);self.assertFalse(report['auto_apply'])
    def test_isotonic_mapping_is_monotone_and_pools_duplicates(self):
        blocks=isotonic_fit([(.7,1),(.8,0),(.8,1),(.9,1)])
        self.assertLessEqual(predict(blocks,.7),predict(blocks,.8))
        self.assertLessEqual(predict(blocks,.8),predict(blocks,.9))
        self.assertEqual(sum(b['n'] for b in blocks),4)
    def test_day_holdout_never_fits_with_heldout_labels(self):
        first=datetime(2026,8,1,tzinfo=timezone.utc);rows=[]
        for d in range(25):
            for h in range(5):
                row=self.row(first+timedelta(days=d),pnl=10 if d<20 and h%2 else -10)
                row['timestamp']=(first+timedelta(days=d,hours=14+h)).isoformat()
                row['exit_timestamp']=(first+timedelta(days=d,hours=14+h,minutes=15)).isoformat();rows.append(row)
        report=analyze(rows,first+timedelta(days=26));seg=report['segments'][0]
        self.assertEqual((seg['train_n'],seg['test_n']),(100,25))
        self.assertLess(seg['train_days'][-1],seg['test_days'][0])
        self.assertEqual(seg['mapping'][0]['probability'],.4)
        self.assertFalse(report['auto_apply'])
