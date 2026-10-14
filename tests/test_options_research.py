import json, sqlite3, tempfile, unittest
from pathlib import Path
from options_research import build_options_research

class OptionsResearchTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name); self.db=self.root/'lab.sqlite'
        with sqlite3.connect(self.db) as cx:
            cx.execute('CREATE TABLE decisions_dashboard(id TEXT PRIMARY KEY,body TEXT NOT NULL)')
        self.a=self.root/'options'/'artifacts'/'intraday'; self.a.mkdir(parents=True)
    def tearDown(self): self.tmp.cleanup()
    def dump(self,name,value): (self.a/name).write_text(json.dumps(value),encoding='utf-8')
    def base(self,status='CLOSED'):
        with sqlite3.connect(self.db) as cx:
            body={'id':'j1','timestamp':'2026-10-15T14:00:10+00:00','session_date':'2026-10-15','symbol':'SPY','side':'PUT','confidence':.72,'status':status,'contract':'SPYX' if status!='SKIP' else None,'pnl':12 if status!='SKIP' else None}
            cx.execute('INSERT INTO decisions_dashboard VALUES(?,?)',('j1',json.dumps(body)))
        self.dump('PAPER_TRADING_LIVE_STATE_V01.json',{'live_ledger':[],'open_positions':[]})
        self.dump('PUT_CONFIRM_LIVE_STATE_V02.json',{'signals':[]})
        self.dump('H09_PUT_FLOW_LIVE_STATE_V01.json',{'signals':[{'signal_id':'h1','candidate_id':'H09B','side':'PUT','decision_date':'2026-10-15','signal_time':'2026-10-15T14:00:00+00:00','contract':'SPY261016P00770000'}]})
        self.dump('H09_PUT_FLOW_PROSPECTIVE_V01.json',{'discovery_cutoff':'2026-10-14','prospective_start_after':'2026-10-14','discovery':{'by_candidate':{'H09B':{'episodes':4,'horizons':{'60':{'n':4,'mean_return':.1,'win_rate':.75,'tp10_before_sl10_rate':.5}}}}},'prospective':{'by_candidate':{}}})
        self.dump('MULTISYMBOL_LIVE_STATE_V01.json',{'signals':[]})
        self.dump('MULTISYMBOL_DISCOVERY_V01.json',{'candidates':[{'id':'MS01','side':'PUT'}],'discovery':{'by_candidate':{'MS01':{'episodes':3,'horizons':{'30':{'n':3,'mean_return':.03,'win_rate':.66}}}},'by_candidate_symbol':{'MS01':{'NVDA':{'episodes':3,'horizons':{'30':{'n':3,'mean_return':.03,'win_rate':.66}}}}}}})
        self.dump('MULTISYMBOL_PROSPECTIVE_V01.json',{'summary':{'by_candidate':{}}})
    def test_bridge_is_read_only_and_separates_evidence(self):
        self.base(); out=build_options_research(self.db,self.root/'options','2026-10-15')
        self.assertTrue(out['read_only']); self.assertFalse(out['broker_actions_enabled']); self.assertEqual(len(out['live_signals']),1)
        groups={x['group']:x['signals'] for x in out['comparison']['groups']}; self.assertEqual(groups['Coinciden'],1)
        h09=[r for r in out['strategy_results'] if r['source']=='H09'][0]
        self.assertEqual(h09['evidence'],'DISCOVERY'); self.assertEqual(h09['mean_return'],.1)
    def test_skipped_jev_direction_is_not_coincidence(self):
        self.base('SKIP'); out=build_options_research(self.db,self.root/'options','2026-10-15')
        groups={x['group']:x['signals'] for x in out['comparison']['groups']}
        self.assertEqual(groups['Coinciden'],0); self.assertEqual(groups['Options solo'],1); self.assertEqual(groups['Jev solo'],0)

if __name__=='__main__': unittest.main()
