import json,sqlite3,unittest
from engine import evaluate
from watch_snapshots import refresh_observations

class WorkerSessionTests(unittest.TestCase):
 def test_finalization_without_new_snapshot_preserves_provider_and_comparison(self):
  ts='2026-10-06T19:50:00Z';contract='SPY261009C00780000'
  snapshot=dict(timestamp=ts,symbol='SPY',features={},contracts=[dict(symbol=contract,side='CALL',bid=1.95,ask=2.,timestamp=ts,volume=10)])
  decision=dict(side='CALL',confidence=.8,probability=.8,model='test',request={'frozen':True},raw={'response':'frozen'})
  row=evaluate(snapshot,decision,[])
  row.update(snapshot=snapshot,comparison={'preserved':True},source_file='original.json',decision_received_at=ts,research_mode='snapshot_shadow',dataset_policy='INTRADAY_LEGACY')
  with sqlite3.connect(':memory:') as db:
   db.execute('CREATE TABLE decisions(id TEXT PRIMARY KEY,body TEXT)');db.execute('CREATE TABLE quotes(symbol TEXT,timestamp TEXT,bid REAL)')
   db.execute('INSERT INTO decisions VALUES(?,?)',(row['id'],json.dumps(row)))
   db.execute('INSERT INTO quotes VALUES(?,?,?)',(contract,'2026-10-06T19:59:00Z',1.96))
   self.assertEqual(refresh_observations(db,'2026-10-06T20:01:00Z'),1)
   new=json.loads(db.execute('SELECT body FROM decisions').fetchone()[0])
   self.assertEqual(new['reason'],'SESSION_CLOSE')
   for field in ('request','raw','snapshot','comparison','source_file','dataset_policy'):self.assertEqual(new[field],row[field])
   self.assertEqual(refresh_observations(db,'2026-10-06T20:02:00Z'),0)
