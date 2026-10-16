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
        self.dump('META_DECISION_LIVE_STATE_V01.json',{'version':'META_DECISION_LIVE_SHADOW_V01','mode':'LIVE_SHADOW_NO_ORDERS','broker_orders_enabled':False,'auto_apply':False,'latest_context':{'captured_at_utc':'2026-10-15T14:00:00+00:00','market_regime':'RISK_OFF'},'recent_decisions':[{'time':'2026-10-15T14:00:00+00:00','day':'2026-10-15','source':'H09','symbol':'SPY','side':'PUT','strategy':'H09B','decision':'ACCEPT','episode_id':'H09:SPY:2026-10-15:E1','persistence_observations':1,'persistence_minutes':0,'market_regime':'RISK_OFF','block_reasons':[],'wait_reasons':[]} ]})
        self.dump('SIGNAL_EPISODE_LIVE_STATE_V01.json',{'version':'SIGNAL_EPISODE_ENGINE_V01','mode':'LIVE_SHADOW_NO_ORDERS','broker_orders_enabled':False,'auto_apply':False,'active_episodes':{'H09:SPY:PUT':{'episode_id':'H09:SPY:2026-10-15:E1','source':'H09','symbol':'SPY','side':'PUT','started_at':'2026-10-15T14:00:00+00:00','last_observation_at':'2026-10-15T14:01:00+00:00','activation_times':['2026-10-15T14:00:00+00:00','2026-10-15T14:01:00+00:00'],'latest_meta_decision':'ACCEPT','ttt_state':'CONFIRMED_PERSISTENCE','hysteresis_state':'CONFIRMED','shadow_decision':'ACCEPT','authorization_emitted':True}},'recent_episodes':[]})
        self.dump('META_ALPACA_PAPER_STATE_V01.json',{'version':'OPTIONS_ALPACA_PAPER_MIRROR_V01','submit_orders':True,'paper_only':True,'updated_at_utc':'2026-10-15T14:05:00+00:00','reconciliation_required':False,'broker_market_open':True,'account':{'status':'ACTIVE','equity':'1998.36','cash':'1800.00','options_buying_power':'1800.00','options_trading_level':3},'broker_positions':[{'symbol':'SPY261016P00770000','qty':'1','side':'long','unrealized_pl':'12.5'}],'trades':{}})
        self.dump('META_PORTFOLIO_LIVE_STATE_V01.json',{'version':'META_PORTFOLIO_LIVE_V01','mode':'LIVE_LOCAL_PAPER','live_start_utc':'2026-10-15T13:25:00+00:00','updated_at_utc':'2026-10-15T14:05:00+00:00','initial_cash':1000.0,'cash':890.0,'equity':950.0,'realized_net_pnl':-50.0,'session_date':'2026-10-15','daily_start_cash':1000.0,'open_positions':[{'signal_id':'META:E1','episode_id':'E1','source':'H09','symbol':'SPY','side':'PUT','status':'OPEN','quantity':1,'contract':'SPY261016P00770000','entry_time':'2026-10-15T14:00:00+00:00','entry_ask':1.1,'unrealized_return':.05}],'live_ledger':[],'policy':{'daily_loss_halt_fraction':.1,'max_global_positions':1,'quantity':1,'ranking_window_seconds':90,'tp_pct':.1,'sl_pct':-.1,'max_horizon_minutes':30,'max_spread_pct':.12,'min_abs_delta':.25,'max_abs_delta':.75,'min_dte':1,'max_dte':10}})
    def test_bridge_is_read_only_and_separates_evidence(self):
        self.base(); out=build_options_research(self.db,self.root/'options','2026-10-15')
        self.assertTrue(out['read_only']); self.assertFalse(out['broker_actions_enabled']); self.assertEqual(len(out['live_signals']),1)
        groups={x['group']:x['signals'] for x in out['comparison']['groups']}; self.assertEqual(groups['Coinciden'],1)
        h09=[r for r in out['strategy_results'] if r['source']=='H09'][0]
        self.assertEqual(h09['evidence'],'DISCOVERY'); self.assertEqual(h09['mean_return'],.1)
        self.assertEqual(out['meta_live']['meta']['session_counts']['ACCEPT'],1)
        self.assertEqual(out['meta_live']['episode_engine']['ttt_confirmed'],1)
        self.assertEqual(out['meta_live']['episode_engine']['would_authorize'],1)
        self.assertTrue(out['meta_alpaca']['read_only']); self.assertTrue(out['meta_alpaca']['broker']['submit_orders'])
        self.assertEqual(out['meta_alpaca']['broker']['equity'],1998.36); self.assertEqual(out['meta_alpaca']['portfolio']['daily_pnl'],-50.0)
        self.assertEqual(out['meta_alpaca']['portfolio']['daily_halt']['state'],'ARMED')
    def test_skipped_jev_direction_is_not_coincidence(self):
        self.base('SKIP'); out=build_options_research(self.db,self.root/'options','2026-10-15')
        groups={x['group']:x['signals'] for x in out['comparison']['groups']}
        self.assertEqual(groups['Coinciden'],0); self.assertEqual(groups['Options solo'],1); self.assertEqual(groups['Jev solo'],0)

if __name__=='__main__': unittest.main()
