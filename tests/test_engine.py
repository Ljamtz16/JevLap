import unittest
from engine import evaluate

class EngineTests(unittest.TestCase):
    def setUp(self):
        self.snapshot=dict(timestamp='2026-10-06T10:00:00-04:00',symbol='SPY',features={},contracts=[dict(symbol='TEST',side='CALL',bid=1.9,ask=2,timestamp='2026-10-06T10:00:00-04:00',volume=50)])
        self.decision=dict(side='CALL',confidence=.8,probability=.9,model='TEST')
    def test_entry_and_bid_exit(self):
        r=evaluate(self.snapshot,self.decision,[dict(symbol='TEST',bid=2.5,timestamp='2026-10-06T10:15:00-04:00')])
        self.assertEqual(r['entry'],2)
        self.assertEqual(r['pnl'],50)
        self.assertEqual(r['reason'],'TP')
    def test_low_confidence_skips(self):
        self.decision['confidence']=.599
        self.assertEqual(evaluate(self.snapshot,self.decision,[])['status'],'SKIP')
    def test_sixty_percent_enters_and_old_threshold_is_preserved(self):
        self.decision['confidence']=.60
        self.assertEqual(evaluate(self.snapshot,self.decision,[])['status'],'OPEN')
        old=dict(threshold=.75,tp=.20,sl=-.10,max_hold=60,max_spread=.15,quantity=1)
        row=evaluate(self.snapshot,self.decision,[],config=old)
        self.assertEqual(row['status'],'SKIP')
        self.assertEqual(row['config']['threshold'],.75)
    def test_future_entry_quote_rejected(self):
        self.snapshot['contracts'][0]['timestamp']='2026-10-06T10:01:00-04:00'
        self.assertIsNone(evaluate(self.snapshot,self.decision,[])['entry'])
    def test_missing_horizon_is_not_zero(self):
        r=evaluate(self.snapshot,self.decision,[])
        self.assertIsNone(r['horizons']['15'])
        self.assertIsNone(r['pnl'])
    def test_stop_first(self):
        r=evaluate(self.snapshot,self.decision,[dict(symbol='TEST',bid=1.7,timestamp='2026-10-06T10:10:00-04:00'),dict(symbol='TEST',bid=3,timestamp='2026-10-06T10:20:00-04:00')])
        self.assertEqual(r['reason'],'SL')
        self.assertEqual(r['pnl'],-30)
    def test_prior_quotes_not_used(self):
        r=evaluate(self.snapshot,self.decision,[dict(symbol='TEST',bid=3,timestamp='2026-10-06T09:59:00-04:00')])
        self.assertEqual(r['status'],'OPEN')

if __name__=='__main__': unittest.main()
