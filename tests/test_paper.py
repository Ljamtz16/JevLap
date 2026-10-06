import unittest,tempfile,os,json
from pathlib import Path
from datetime import timedelta
from unittest.mock import patch
from paper_executor import Executor,now,price,PaperAPI
class FakeAPI:
 def __init__(self):self.calls=[];self.lookup={};self.positions=[];self.orders=[];self.fail=False
 def by_client(self,cid):return self.lookup.get(cid)
 def quote(self,symbol):return {'bp':1.4,'ap':1.45,'t':now().isoformat()}
 def request(self,path,method='GET',body=None):
  self.calls.append((path,method,body))
  if path=='/v2/account':return {'id':'paper-test','equity':'1000','options_buying_power':'1000','status':'ACTIVE','trading_blocked':False,'options_trading_level':3}
  if path=='/v2/clock':return {'timestamp':now().isoformat(),'next_close':(now()+timedelta(hours=3)).isoformat(),'is_open':True}
  if path=='/v2/positions':return self.positions
  if path.startswith('/v2/orders?'):return self.orders
  if path.startswith('/v2/options/contracts/'):return {'tradable':True,'status':'active','size':'100','type':'call','underlying_symbol':'SPY','expiration_date':'2099-01-01'}
  if path=='/v2/orders' and method=='POST':
   if self.fail:raise TimeoutError()
   order=dict(body,id='broker1',status='new',created_at=now().isoformat());self.lookup[body['client_order_id']]=order;return order
  return None
class PaperTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.api=FakeAPI();self.exe=Executor(self.api,Path(self.tmp.name)/'db',True)
  self.env=patch.dict(os.environ,{'JEV_PAPER_ACCOUNT_ID':'paper-test'});self.env.start()
  self.row={'id':'abcdefgh','side':'CALL','confidence':.8,'timestamp':now().isoformat(),'decision_received_at':now().isoformat(),'contract':'SPY261009C00690000','symbol':'SPY','research_mode':'snapshot_shadow'}
 def tearDown(self):self.exe.db.close();self.tmp.cleanup();self.env.stop()
 def posts(self):return [c for c in self.api.calls if c[1]=='POST']
 def test_paper_endpoint_fixed(self):self.assertEqual(PaperAPI.trading,'https://paper-api.alpaca.markets')
 def test_disabled_never_sends(self):self.exe.enabled=False;self.exe.tick([self.row]);self.assertEqual(self.posts(),[])
 def test_single_entry_idempotent(self):
  self.exe.tick([self.row]);self.exe.tick([self.row]);self.assertEqual(len(self.posts()),1);self.assertEqual(self.posts()[0][2]['position_intent'],'buy_to_open')
 def test_uncertain_submit_never_repeats(self):
  self.api.fail=True
  with self.assertRaises(TimeoutError):self.exe.tick([self.row])
  self.api.fail=False;self.exe.tick([self.row]);self.assertEqual(len(self.posts()),1)
 def test_stale_decision_rejected(self):self.row['timestamp']=(now()-timedelta(minutes=3)).isoformat();self.exe.tick([self.row]);self.assertEqual(self.posts(),[])
 def test_foreign_position_blocks_entry(self):self.api.positions=[{'symbol':'OTHER'}];self.exe.tick([self.row]);self.assertEqual(self.posts(),[])
 def test_account_pin(self):
  with patch.dict(os.environ,{'JEV_PAPER_ACCOUNT_ID':'wrong'}):
   with self.assertRaises(ValueError):self.exe.tick([self.row])
  self.assertEqual(self.posts(),[])
 def test_exit_uses_fill_and_sell_to_close(self):
  cid='jv-entry-abcdefgh';order={'symbol':self.row['contract'],'status':'filled','filled_qty':'1','filled_avg_price':'1.0','filled_at':now().isoformat(),'created_at':now().isoformat(),'client_order_id':cid}
  self.exe.db.execute('INSERT INTO intents VALUES(?,?,?,?,?)',(cid,json.dumps({'symbol':self.row['contract']}),json.dumps(order),'filled',now().isoformat()));self.exe.db.commit()
  self.api.positions=[{'symbol':self.row['contract'],'asset_class':'us_option','qty':'1'}]
  self.exe.tick([]);self.assertEqual(self.posts()[0][2]['position_intent'],'sell_to_close')
 def test_rounding(self):self.assertEqual(price(1.43,True),'1.45');self.assertEqual(price(1.43),'1.40')

 def test_pending_exit_does_not_duplicate(self):
  cid='jv-entry-abcdefgh';order={'symbol':self.row['contract'],'status':'filled','filled_qty':'1','filled_avg_price':'1.0','filled_at':now().isoformat(),'created_at':now().isoformat(),'client_order_id':cid}
  self.exe.db.execute('INSERT INTO intents VALUES(?,?,?,?,?)',(cid,json.dumps({'symbol':self.row['contract']}),json.dumps(order),'filled',now().isoformat()));self.exe.db.commit()
  self.api.positions=[{'symbol':self.row['contract'],'asset_class':'us_option','qty':'1'}]
  self.api.orders=[{'symbol':self.row['contract'],'client_order_id':'jv-exit-abcdefgh-0','status':'new','created_at':now().isoformat(),'id':'exit-id'}]
  self.exe.tick([]);self.assertEqual(self.posts(),[])
 def test_premium_above_200_allowed_for_one_contract(self):
  self.api.quote=lambda s:{'bp':2.9,'ap':3,'t':now().isoformat()}
  self.exe.tick([self.row]);self.assertEqual(len(self.posts()),1)
  self.assertEqual(self.posts()[0][2]['qty'],'1');self.assertEqual(float(self.posts()[0][2]['limit_price']),3.0)
 def test_insufficient_buying_power_blocks_entry(self):
  self.api.quote=lambda s:{'bp':10.9,'ap':11,'t':now().isoformat()}
  self.exe.tick([self.row]);self.assertEqual(self.posts(),[])
 def test_stale_quote_blocks_order(self):
  self.api.quote=lambda s:(_ for _ in ()).throw(ValueError('Stale quote'))
  with self.assertRaises(ValueError):self.exe.tick([self.row])
  self.assertEqual(self.posts(),[])

 def test_filled_entry_before_position_visible_blocks_second(self):
  cid='jv-entry-old';order={'symbol':self.row['contract'],'status':'filled','filled_qty':'1','filled_avg_price':'1.0','filled_at':now().isoformat(),'created_at':now().isoformat(),'client_order_id':cid}
  self.exe.db.execute('INSERT INTO intents VALUES(?,?,?,?,?)',(cid,json.dumps({'symbol':self.row['contract']}),json.dumps(order),'filled',now().isoformat()));self.exe.db.commit()
  self.exe.tick([self.row]);self.assertEqual(self.posts(),[])
