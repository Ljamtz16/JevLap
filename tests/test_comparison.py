import hashlib,json,sqlite3,tempfile,unittest
from pathlib import Path
from datetime import datetime,timezone
from contextlib import closing
from compare_system import Comparator
from engine import evaluate,CONFIG
from snapshot_adapter import adapt

class ComparisonTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        # Repository source fixture copied into tests: frozen definitions and pure functions.
        self.c=Comparator(Path(__file__).parent/'fixtures/options-system',self.root/'lab.sqlite')
        self.envelope=self.make_envelope()
    def tearDown(self):self.tmp.cleanup()
    def make_envelope(self):
        options={}
        for cp,iv in [('C',.2),('P',.205)]:
            options['SPY261009'+cp+'00100000']={'impliedVolatility':iv,'dailyBar':{'v':100},'latestQuote':{'bp':1.,'ap':1.05,'t':'2026-10-06T14:00:00Z'}}
        payload={'market_date':'2026-10-06','market_clock':{'is_open':True},'global_context':{'cross_market':{'spy_from_open':-.003,'iwm_from_open':-.004}},'symbols':{'SPY':{'spot':100.,'option_snapshot':{'snapshots':options}},'QQQ':{'spot':100.}}}
        digest=hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
        return {'payload':payload,'sha256':digest,'captured_at_utc':'2026-10-06T14:00:00+00:00'}
    def signal(self,previous=None):
        return self.c.signal(self.envelope,'SPY',previous,datetime(2026,10,6,14,0,30,tzinfo=timezone.utc))
    def test_scope_freeze_missing_and_activation(self):
        signal=self.signal()
        self.assertEqual(signal['side'],'CALL');self.assertEqual(signal['evaluation_mode'],'PROSPECTIVE')
        self.assertEqual(signal['hypotheses'][0]['id'],'H03_CALL_RELATIVE_WEAKNESS_REVERSAL_V01')
        self.assertEqual(len(signal['auxiliary_15m']),1)
        self.assertIsNone(self.c.signal(self.envelope,'QQQ')['side'])
        self.envelope['payload']['global_context']['cross_market']={}
        self.assertEqual(self.signal()['status'],'MISSING_FEATURES')
        self.envelope['payload']['market_date']='2026-10-02'
        self.assertEqual(self.signal()['status'],'PRE_FREEZE')
    def test_no_trade_only_when_all_rules_evaluable(self):
        self.envelope['payload']['global_context']['cross_market']={'spy_from_open':0.,'iwm_from_open':0.}
        prev={'market_date':'2026-10-06','timestamp':'2026-10-06T13:59:00+00:00','features':{'atm_iv':.3,'put_call_iv_skew':.005,'put_call_volume_ratio_1pct':1.}}
        self.assertEqual(self.signal(prev)['side'],'NO_TRADE')
        prev['timestamp']='2026-10-06T14:01:00+00:00'
        self.assertEqual(self.signal(prev)['status'],'MISSING_FEATURES')
    def test_historical_replay_marked(self):
        self.assertEqual(self.c.signal(self.envelope,'SPY',now=datetime(2026,10,6,15,tzinfo=timezone.utc))['evaluation_mode'],'RECONSTRUCTED')
    def test_join_threshold_outcomes_and_provider_preserved(self):
        state=adapt(self.envelope)[0][0]
        decision=dict(side='PUT',confidence=.3,probability=.6,model='jev',request={'state':{}},raw={'provider':True})
        row=evaluate(state,decision,[]);row.update(snapshot=state,source_file='sample.json',comparison=None)
        signal=self.signal();signal['source_file']='sample.json'
        with closing(sqlite3.connect(self.c.db_path)) as db,db:
            db.execute('CREATE TABLE decisions(id TEXT PRIMARY KEY,body TEXT)')
            db.execute('CREATE TABLE quotes(symbol TEXT,timestamp TEXT,bid REAL)')
            db.execute('INSERT INTO decisions VALUES(?,?)',(row['id'],json.dumps(row)))
            db.execute('INSERT INTO comparison_signals VALUES(?,?,?)',(row['timestamp'],row['symbol'],json.dumps(signal)))
            db.execute('INSERT INTO quotes VALUES(?,?,?)',('SPY261009C00100000','2026-10-06T14:15:00+00:00',1.3))
        self.assertEqual(self.c.update(),1)
        with closing(sqlite3.connect(self.c.db_path)) as db:
            updated=json.loads(db.execute('SELECT body FROM decisions').fetchone()[0])
        self.assertEqual(updated['comparison']['group'],'Sistema solo')
        self.assertEqual(updated['comparison']['system_simulation']['status'],'CLOSED')
        self.assertEqual(updated['comparison']['system_simulation']['pnl'],25.)
        for key in ('request','raw','snapshot','confidence','side','status'):
            self.assertEqual(updated[key],row[key])
        self.assertEqual(self.c.update(),0)
    def test_bad_checksum_never_imported(self):
        source=self.root/'raw';source.mkdir()
        self.envelope['sha256']='invalid'
        (source/'intraday_options_1.json').write_text(json.dumps(self.envelope))
        self.c.scan(source)
        with closing(sqlite3.connect(self.c.db_path)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM comparison_signals').fetchone()[0],0)

if __name__=='__main__':unittest.main()
