import unittest,json,hashlib
from snapshot_adapter import adapt
class AdapterTests(unittest.TestCase):
 def envelope(self):
  p={'symbols':{'SPY':{'spot':690,'stock_snapshot':{},'option_snapshot':{'snapshots':{'SPY261009C00690000':{'latestQuote':{'bp':1.4,'ap':1.5,'t':'2026-10-06T14:00:00Z'},'dailyBar':{'v':100}}}}}},'market_clock':{'is_open':True}}
  return {'payload':p,'sha256':hashlib.sha256(json.dumps(p,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest(),'captured_at_utc':'2026-10-06T14:00:01+00:00'}
 def test_contract_side_and_quote(self):
  states,quotes,is_open=adapt(self.envelope());self.assertTrue(is_open);self.assertEqual(states[0]['contracts'][0]['side'],'CALL');self.assertEqual(quotes[0]['bid'],1.4)
 def test_checksum(self):
  e=self.envelope();e['payload']['symbols']['SPY']['spot']=0
  with self.assertRaises(ValueError):adapt(e)
 def test_future_quote_not_used(self):
  e=self.envelope();e['captured_at_utc']='2026-10-06T13:00:00+00:00'
  states,quotes,_=adapt(e);self.assertEqual(quotes,[]);self.assertEqual(states[0]['contracts'],[])
