import unittest
from engine import evaluate

class SessionTests(unittest.TestCase):
 def setUp(self):
  self.ts='2026-10-06T19:50:00Z';self.contract='SPY261009C00780000'
  self.snapshot=dict(timestamp=self.ts,symbol='SPY',features={'spot':780.},contracts=[dict(symbol=self.contract,side='CALL',bid=1.95,ask=2.,timestamp=self.ts,volume=10,bid_size=10,ask_size=10)])
  self.decision=dict(side='CALL',confidence=.8,probability=.8,model='test')
 def quote(self,ts,bid=1.96):return dict(symbol=self.contract,timestamp=ts,bid=bid)
 def test_session_close_and_unknown_horizon(self):
  r=evaluate(self.snapshot,self.decision,[self.quote('2026-10-06T19:59:05Z')],as_of='2026-10-06T20:01:00Z')
  self.assertEqual((r['status'],r['reason'],r['pnl']),('CLOSED','SESSION_CLOSE',-4.));self.assertIsNone(r['horizons']['15'])
  self.assertEqual(r['exit_timestamp'],'2026-10-06T19:59:05+00:00')
 def test_next_day_never_closes(self):
  r=evaluate(self.snapshot,self.decision,[self.quote('2026-10-07T14:00:00Z',3)])
  self.assertEqual(r['status'],'INCOMPLETE');self.assertIsNone(r['pnl']);self.assertIsNone(r['mae']);self.assertTrue(all(v is None for v in r['horizons'].values()))
 def test_expired_without_quote_is_unknown(self):
  self.contract='SPY261006C00780000';self.snapshot['contracts'][0]['symbol']=self.contract
  r=evaluate(self.snapshot,self.decision,[],as_of='2026-10-06T20:01:00Z')
  self.assertEqual(r['status'],'EXPIRED');self.assertIsNone(r['pnl'])
 def test_expired_with_bid_closes_without_settlement(self):
  self.contract='SPY261006C00780000';self.snapshot['contracts'][0]['symbol']=self.contract
  r=evaluate(self.snapshot,self.decision,[self.quote('2026-10-06T19:59:05Z')],as_of='2026-10-07T14:00:00Z')
  self.assertEqual(r['reason'],'SESSION_CLOSE');self.assertEqual(r['pnl'],-4.)
 def test_stale_close_is_incomplete(self):
  r=evaluate(self.snapshot,self.decision,[self.quote('2026-10-06T19:55:00Z')],as_of='2026-10-06T20:01:00Z')
  self.assertEqual(r['status'],'INCOMPLETE');self.assertIsNone(r['pnl'])
 def test_as_of_excludes_future(self):
  r=evaluate(self.snapshot,self.decision,[self.quote('2026-10-06T19:59:05Z',3)],as_of='2026-10-06T19:55:00Z')
  self.assertEqual(r['status'],'OPEN');self.assertIsNone(r['pnl'])
 def test_after_hours_excluded(self):
  r=evaluate(self.snapshot,self.decision,[self.quote('2026-10-06T20:01:00Z',3)],as_of='2026-10-06T20:02:00Z')
  self.assertEqual(r['status'],'INCOMPLETE')
 def test_early_close(self):
  self.snapshot['timestamp']='2026-11-27T17:50:00Z';self.snapshot['contracts'][0]['timestamp']=self.snapshot['timestamp']
  self.contract='SPY261130C00780000';self.snapshot['contracts'][0]['symbol']=self.contract;self.snapshot['session_close_at_utc']='2026-11-27T18:00:00Z'
  r=evaluate(self.snapshot,self.decision,[self.quote('2026-11-27T17:59:00Z')],as_of='2026-11-27T18:01:00Z')
  self.assertEqual(r['reason'],'SESSION_CLOSE')
 def test_entry_outside_session_skipped(self):
  self.snapshot['timestamp']='2026-10-06T20:01:00Z'
  r=evaluate(self.snapshot,self.decision,[]);self.assertEqual((r['status'],r['reason']),('SKIP','OUTSIDE_SESSION'))
 def test_stop_before_close_unchanged(self):
  r=evaluate(self.snapshot,self.decision,[self.quote('2026-10-06T19:55:00Z',1.7),self.quote('2026-10-06T19:59:00Z',2.)],as_of='2026-10-06T20:01:00Z')
  self.assertEqual(r['reason'],'SL');self.assertEqual(r['pnl'],-30.)
 def test_dst_boundary(self):
  self.snapshot['timestamp']='2026-11-02T20:50:00Z';self.snapshot['contracts'][0]['timestamp']=self.snapshot['timestamp']
  self.contract='SPY261106C00780000';self.snapshot['contracts'][0]['symbol']=self.contract
  r=evaluate(self.snapshot,self.decision,[self.quote('2026-11-02T20:59:00Z')],as_of='2026-11-02T21:01:00Z')
  self.assertEqual(r['reason'],'SESSION_CLOSE');self.assertEqual(r['session_close_at_utc'],'2026-11-02T16:00:00-05:00')
