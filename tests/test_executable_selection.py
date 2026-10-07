import unittest
from engine import evaluate


class ExecutableSelectionTests(unittest.TestCase):
    def test_new_policy_selects_affordable_contract_and_preserves_threshold(self):
        ts='2026-10-07T14:00:00Z'
        c=dict(symbol='SPY261009C00100000',side='CALL',bid=1.45,ask=1.5,timestamp=ts,
               volume=100,bid_size=10,ask_size=10,delta=.5)
        state=dict(timestamp=ts,symbol='SPY',features={'spot':100},contracts=[c])
        decision=dict(side='CALL',confidence=.8,probability=.9,model='TEST')
        result=evaluate(state,decision,[])
        self.assertEqual(result['contract_selection']['version'],'executable_contract_v1')
        self.assertEqual(result['capital_required'],150)
        self.assertEqual(result['entry_quote_timestamp'],ts)
        self.assertEqual(result['config']['threshold'],.60)
        c['ask']=2.5;c['bid']=2.45
        self.assertIsNone(evaluate(state,decision,[])['entry'])
    def test_frozen_legacy_config_not_replaced(self):
        ts='2026-10-07T14:00:00Z'
        state=dict(timestamp=ts,symbol='SPY',features={},contracts=[dict(symbol='TEST',side='CALL',
                   bid=2.9,ask=3.,timestamp=ts,volume=1)])
        cfg=dict(threshold=.75,tp=.2,sl=-.1,max_hold=60,max_spread=.15,quantity=1)
        result=evaluate(state,dict(side='CALL',confidence=.8),[],config=cfg)
        self.assertEqual(result['config'],cfg);self.assertEqual(result['contract'],'TEST')
