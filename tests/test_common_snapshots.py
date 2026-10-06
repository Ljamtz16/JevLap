import hashlib,json,tempfile,unittest,sqlite3
from pathlib import Path
from snapshot_adapter import adapt
from source_snapshots import allowed_symbols,snapshot_paths
from compare_system import Comparator

class CommonSnapshotTests(unittest.TestCase):
 def envelope(self):
  clock=dict(is_open=True,timestamp='2026-10-07T10:00:00-04:00',next_close='2026-10-07T20:00:00Z')
  chain={'snapshots':{f'SPY261009{cp}00100000':dict(impliedVolatility=iv,dailyBar={'v':100},latestQuote={'bp':1.,'ap':1.05,'t':'2026-10-07T14:00:00Z'}) for cp,iv in [('C',.2),('P',.205)]}}
  p=dict(schema_version='o1.4',market_clock=clock,underlying={'symbol':'SPY','snapshot':{'latestTrade':{'p':100.,'t':'2026-10-07T14:00:00Z'}}},options={'snapshot':chain},cross_market={'features':{'spy_from_open':-.003,'iwm_from_open':-.004}},research_state={'secret_baseline':'DO_NOT_FORWARD'})
  digest=hashlib.sha256(json.dumps(p,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
  return dict(payload=p,sha256=digest,capture_id='same_capture',captured_at_utc='2026-10-07T14:00:01Z')
 def test_same_hash_timestamp_and_no_baseline_leak(self):
  e=self.envelope();states,quotes,is_open=adapt(e)
  self.assertEqual(states[0]['snapshot_sha256'],e['sha256']);self.assertEqual(states[0]['timestamp'],e['captured_at_utc'])
  self.assertEqual(len(states[0]['contracts']),2);self.assertEqual(len(quotes),2)
  self.assertNotIn('research_state',states[0]);self.assertNotIn('secret_baseline',str(states[0]));self.assertEqual(states[0]['session_close_at_utc'],'2026-10-07T20:00:00Z')
 def test_routing_preserves_previous_day(self):
  e=self.envelope();e['payload']['symbols']={'SPY':{},'QQQ':{}}
  self.assertEqual(allowed_symbols(e,'INTRADAY_LEGACY'),{'QQQ'});self.assertEqual(allowed_symbols(e,'SPY_PROSPECTIVE_CANONICAL_V1'),{'SPY'})
  e['captured_at_utc']='2026-10-06T14:00:00Z'
  self.assertEqual(allowed_symbols(e,'INTRADAY_LEGACY'),{'SPY','QQQ'});self.assertEqual(allowed_symbols(e,'SPY_PROSPECTIVE_CANONICAL_V1'),set())
 def test_comparator_reads_same_capture(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);raw=root/'intraday';canonical=root/'prospective';raw.mkdir();canonical.mkdir()
   e=self.envelope();(canonical/'spy_options_20261007T140001.json').write_text(json.dumps(e))
   c=Comparator(Path(__file__).parent/'fixtures/options-system',root/'lab.sqlite');c.scan(raw)
   with sqlite3.connect(c.db_path) as db:signals=[json.loads(r[0]) for r in db.execute('SELECT body FROM comparison_signals')]
   self.assertEqual(len(signals),1);self.assertEqual(signals[0]['snapshot_sha256'],e['sha256']);self.assertEqual(signals[0]['dataset_policy'],'SPY_PROSPECTIVE_CANONICAL_V1')
   self.assertAlmostEqual(signals[0]['features']['put_call_iv_skew'],.005)
 def test_bad_hash_fails_closed(self):
  e=self.envelope();e['sha256']='bad'
  with self.assertRaises(ValueError):adapt(e)
 def test_cross_source_order(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);raw=root/'intraday';canonical=root/'prospective';raw.mkdir();canonical.mkdir()
   (raw/'intraday_options_20261007T140002.json').touch();(canonical/'spy_options_20261007T140001.json').touch()
   self.assertEqual(snapshot_paths(raw)[0][0].name,'spy_options_20261007T140001.json')
