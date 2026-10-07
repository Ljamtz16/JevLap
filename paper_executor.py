"""Long-option PAPER executor. Endpoint is deliberately not configurable."""
import argparse,json,os,re,sqlite3,time,urllib.request,urllib.error,urllib.parse
from datetime import datetime,timezone
from decimal import Decimal,ROUND_CEILING,ROUND_FLOOR
from pathlib import Path
from engine import CONFIG
from credentials import load
ROOT=Path(__file__).resolve().parent
TERMINAL={'filled','canceled','expired','rejected','replaced','done_for_day'}

def now():return datetime.now(timezone.utc)
def stamp(s):return datetime.fromisoformat(s.replace('Z','+00:00'))
def fresh(s,limit=30):return 0<=(now()-stamp(s)).total_seconds()<=limit
def price(value,buy=False):
    v=Decimal(str(value));tick=Decimal('.05') if v<3 else Decimal('.10')
    return str((v/tick).to_integral_value(rounding=ROUND_CEILING if buy else ROUND_FLOOR)*tick)

class ApiError(Exception):
    def __init__(self,code):self.code=code;super().__init__('Alpaca HTTP '+str(code))
class PaperAPI:
    trading='https://paper-api.alpaca.markets'
    data='https://data.alpaca.markets'
    def request(self,path,method='GET',body=None,data=False):
        headers={'APCA-API-KEY-ID':os.environ['ALPACA_PAPER_API_KEY'],'APCA-API-SECRET-KEY':os.environ['ALPACA_PAPER_SECRET_KEY'],'Content-Type':'application/json'}
        req=urllib.request.Request((self.data if data else self.trading)+path,None if body is None else json.dumps(body).encode(),headers,method=method)
        try:
            with urllib.request.urlopen(req,timeout=10) as response:
                raw=response.read();return json.loads(raw) if raw else None
        except urllib.error.HTTPError as exc:raise ApiError(exc.code) from None
    def quote(self,symbol):
        feed=os.getenv('JEV_OPTIONS_FEED','opra')
        obj=self.request('/v1beta1/options/quotes/latest?'+urllib.parse.urlencode({'symbols':symbol,'feed':feed}),data=True)
        q=obj['quotes'][symbol]
        if not fresh(q['t']) or not 0<float(q['bp'])<=float(q['ap']):raise ValueError('Missing, stale or invalid quote')
        return q
    def by_client(self,cid):
        try:return self.request('/v2/orders:by_client_order_id?'+urllib.parse.urlencode({'client_order_id':cid}))
        except ApiError as e:
            if e.code==404:return None
            raise

class Executor:
    def __init__(self,api,dbpath=None,enabled=False):
        self.api=api;self.enabled=enabled
        self.db=sqlite3.connect(dbpath or ROOT/'data/paper.sqlite',timeout=20)
        self.db.execute('CREATE TABLE IF NOT EXISTS intents(cid TEXT PRIMARY KEY,body TEXT NOT NULL,broker TEXT,state TEXT NOT NULL,created TEXT NOT NULL)')
        self.db.execute('CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL)');self.db.commit()
        self.snapshot={}
    def meta(self,key,value=None):
        if value is not None:
            self.db.execute('INSERT OR REPLACE INTO meta VALUES(?,?)',(key,str(value)));self.db.commit()
        row=self.db.execute('SELECT value FROM meta WHERE key=?',(key,)).fetchone();return row[0] if row else None
    def event(self,message):print(message,flush=True)
    def submit(self,cid,payload):
        # Persist BEFORE network I/O. Uncertain calls are only reconciled, never blindly repeated.
        if not self.enabled:return None
        if self.db.execute('SELECT 1 FROM intents WHERE cid=?',(cid,)).fetchone():return None
        self.db.execute('INSERT INTO intents VALUES(?,?,NULL,?,?)',(cid,json.dumps(payload),'PREPARED',now().isoformat()));self.db.commit()
        try:
            broker=self.api.request('/v2/orders','POST',payload)
            self.db.execute('UPDATE intents SET broker=?,state=? WHERE cid=?',(json.dumps(broker),broker['status'],cid));self.db.commit()
            self.event('ORDER '+cid+' '+broker['status']);return broker
        except Exception:
            self.db.execute('UPDATE intents SET state=? WHERE cid=?',('UNCERTAIN',cid));self.db.commit()
            raise
    def reconcile(self):
        for cid,raw,broker,state,created in self.db.execute('SELECT * FROM intents').fetchall():
            if state in TERMINAL:continue
            order=self.api.by_client(cid)
            if order:
                self.db.execute('UPDATE intents SET broker=?,state=? WHERE cid=?',(json.dumps(order),order['status'],cid))
            elif state in ('PREPARED','UNCERTAIN'):
                self.event('UNCERTAIN '+cid+' — entries blocked, manual review required')
        self.db.commit()
    def tick(self,decisions=()):
        self.reconcile()
        account=self.api.request('/v2/account')
        pinned=os.getenv('JEV_PAPER_ACCOUNT_ID','')
        if not pinned or account['id']!=pinned:raise ValueError('Paper account identity not pinned or mismatched')
        clock=self.api.request('/v2/clock')
        positions=self.api.request('/v2/positions')
        orders=self.api.request('/v2/orders?status=open&limit=500')
        rows=self.db.execute('SELECT * FROM intents').fetchall()
        own_symbols={json.loads(body)['symbol'] for cid,body,*_ in rows if cid.startswith('jv-entry-')}
        broker_time=stamp(clock['timestamp']);session_day=broker_time.astimezone(__import__('zoneinfo').ZoneInfo('America/New_York')).date().isoformat()
        if self.meta('session_day')!=session_day:
            self.meta('session_day',session_day);self.meta('start_equity',account['equity'])
        drawdown=float(account['equity'])-float(self.meta('start_equity'))
        if drawdown<=-50:self.meta('halt:'+session_day,'true')
        minutes_left=(stamp(clock['next_close'])-broker_time).total_seconds()/60
        self.snapshot={'checked_at':now().isoformat(),'enabled':self.enabled,'equity':account['equity'],'buying_power':account.get('options_buying_power'), 'daily_equity_change':round(drawdown,2),'positions':positions,'open_orders':orders,'mode':'ALPACA_PAPER','account_kind':'BROKER_PAPER','account_verified':True}
        closed=[]
        unclosed_fill=False
        for cid,body,b,state,created in rows:
            if not cid.startswith('jv-entry-') or not b:continue
            entry_fill=json.loads(b)
            if float(entry_fill.get('filled_qty',0))!=1 or not entry_fill.get('filled_avg_price'):continue
            prefix=cid.replace('jv-entry-','jv-exit-')+'-'
            exit_fills=[json.loads(eb) for ec,_,eb,_,_ in rows if ec.startswith(prefix) and eb and float(json.loads(eb).get('filled_qty',0))==1 and json.loads(eb).get('filled_avg_price')]
            if exit_fills:closed.append(round((float(exit_fills[0]['filled_avg_price'])-float(entry_fill['filled_avg_price']))*100,2))
            else:unclosed_fill=True
        self.snapshot.update(realized_pnl_gross=round(sum(closed),2),closed_trades=len(closed),win_rate=None if not closed else round(sum(p>0 for p in closed)/len(closed)*100,2),unrealized_pnl=sum(float(p.get('unrealized_pl',0)) for p in positions if p['symbol'] in own_symbols))
        # Cancel old or end-of-session buy orders, then wait for terminal acknowledgement.
        for order in orders:
            if order.get('client_order_id','').startswith('jv-entry-') and ((now()-stamp(order['created_at'])).total_seconds()>60 or not clock['is_open'] or minutes_left<=15):
                if self.enabled and order['status']!='pending_cancel':self.api.request('/v2/orders/'+order['id'],'DELETE')
        # Exits stay independent of Jev and entry risk limits.
        for pos in positions:
            if pos['symbol'] not in own_symbols:continue
            if pos.get('asset_class')!='us_option' or float(pos['qty'])!=1:raise ValueError('Unexpected owned position; manual review required')
            if not clock['is_open']:
                self.event('MARKET_CLOSED holding '+pos['symbol']);continue
            fills=[json.loads(b) for cid,body,b,state,created in rows if b and cid.startswith('jv-entry-') and json.loads(body)['symbol']==pos['symbol'] and float(json.loads(b).get('filled_qty',0))>0]
            if not fills:raise ValueError('Owned position without confirmed entry fill')
            entry_order=max(fills,key=lambda o:o.get('filled_at') or o['created_at'])
            entry=float(entry_order['filled_avg_price']);start=stamp(entry_order['filled_at'])
            try:q=self.api.quote(pos['symbol'])
            except Exception:
                self.event('EXIT_QUOTE_UNAVAILABLE '+pos['symbol']);continue
            ret=float(q['bp'])/entry-1
            reason='EOD' if minutes_left<=10 else 'TIME' if (now()-start).total_seconds()>=3600 else 'TP' if ret>=.20 else 'SL' if ret<=-.10 else None
            latch='exit_reason:'+entry_order['client_order_id']
            reason=self.meta(latch) or reason
            if not reason:continue
            if self.enabled:self.meta(latch,reason)
            related=[o for o in orders if o['symbol']==pos['symbol']]
            if related:
                # Do not duplicate exits. Reprice via cancel-confirm-resubmit.
                for order in related:
                    if order.get('client_order_id','').startswith('jv-exit-') and (now()-stamp(order['created_at'])).total_seconds()>30 and order['status']!='pending_cancel':
                        if self.enabled:self.api.request('/v2/orders/'+order['id'],'DELETE')
                continue
            if any(state not in TERMINAL and json.loads(body)['symbol']==pos['symbol'] for cid,body,b,state,created in rows):continue
            base=entry_order['client_order_id'].replace('jv-entry-','jv-exit-')
            count=sum(cid.startswith(base) for cid,*_ in rows)
            cid=base+'-'+str(count)
            self.submit(cid,dict(symbol=pos['symbol'],qty='1',side='sell',position_intent='sell_to_close',type='limit',limit_price=price(q['bp']),time_in_force='day',client_order_id=cid))
            self.event('EXIT '+reason+' '+pos['symbol'])
        unresolved=any(state not in TERMINAL for _,_,_,state,_ in rows)
        daily_entries=sum(cid.startswith('jv-entry-') and stamp(created).astimezone(__import__('zoneinfo').ZoneInfo('America/New_York')).date().isoformat()==session_day for cid,_,_,_,created in rows)
        if not self.enabled or positions or orders or unresolved or unclosed_fill or not clock['is_open'] or minutes_left<=15 or self.meta('halt:'+session_day)=='true' or daily_entries>=3:return
        if account['status']!='ACTIVE' or account.get('trading_blocked') or int(account.get('options_trading_level',0))<2:return
        # Newest snapshot, then highest confidence; baseline never influences selection.
        for row in sorted(decisions,key=lambda r:(r.get('decision_received_at',''),r['confidence']),reverse=True):
            if row.get('research_mode')!='snapshot_shadow' or not row.get('contract') or row['side'] not in ('CALL','PUT') or row['confidence']<CONFIG['threshold']:continue
            if not fresh(row['timestamp'],120) or not fresh(row['decision_received_at'],120):continue
            cid='jv-entry-'+row['id']
            if self.db.execute('SELECT 1 FROM intents WHERE cid=?',(cid,)).fetchone():continue
            symbol=row['contract']
            if not re.fullmatch(r'[A-Z]+\d{6}[CP]\d{8}',symbol):continue
            contract=self.api.request('/v2/options/contracts/'+symbol)
            if not contract.get('tradable') or contract.get('status')!='active' or int(contract.get('size',0))!=100:continue
            if contract.get('underlying_symbol')!=row['symbol'] or contract.get('type')!=('call' if row['side']=='CALL' else 'put'):continue
            # Avoid expiry-day broker liquidation for v0.1.
            if contract['expiration_date']<=session_day:continue
            q=self.api.quote(symbol);bid=float(q['bp']);ask=float(q['ap'])
            if row.get('config',{}).get('contract_selection_version')=='executable_contract_v1':
                from datetime import date
                dte=(date.fromisoformat(contract['expiration_date'])-date.fromisoformat(session_day)).days
                policy=row.get('contract_selection',{}).get('policy') or {}
                if not policy.get('min_dte',1)<=dte<=policy.get('max_dte',10):continue
                if float(q.get('bs') or 0)<1 or float(q.get('as') or 0)<1:continue
            if (ask-bid)/ask>.15:continue
            limit=price(ask,True);cost=float(limit)*100
            bp=float(account.get('options_buying_power') or 0)
            fraction=float(os.getenv('JEV_PAPER_PREMIUM_FRACTION','.20'))
            cash=float(account.get('cash') or account['equity'])
            if not 0<fraction<=1 or cost>min(bp,cash*fraction) or cost<=0:continue
            self.submit(cid,dict(symbol=symbol,qty='1',side='buy',position_intent='buy_to_open',type='limit',limit_price=limit,time_in_force='day',client_order_id=cid))
            break

def run(check=False,probe=None):
    load();ROOT.joinpath('data').mkdir(exist_ok=True)
    api=PaperAPI()
    if check:
        a=api.request('/v2/account');c=api.request('/v2/clock')
        (ROOT/'data/paper-account.json').write_text(json.dumps({'account_id':a['id'],'equity':a['equity'],'options_trading_level':a.get('options_trading_level'),'checked_at':now().isoformat()}),encoding='utf-8')
        if probe:
            q=api.quote(probe)
            print(json.dumps({'quote_check':'OK','symbol':probe,'quote_timestamp':q['t'],'feed':os.getenv('JEV_OPTIONS_FEED','opra')}))
        print(json.dumps({'paper_account_id' :a['id'],'status':a['status'],'equity':a['equity'],'options_trading_level':a.get('options_trading_level'),'market_open':c['is_open']}));return
    enabled=os.getenv('JEV_PAPER_ENABLED','false').lower()=='true'
    lock_file=open(ROOT/'data/paper-executor.lock','a+b')
    if os.name=='nt':
        import msvcrt
        lock_file.seek(0);lock_file.write(b'0');lock_file.flush();lock_file.seek(0)
        msvcrt.locking(lock_file.fileno(),msvcrt.LK_NBLCK,1)
    else:
        import fcntl
        fcntl.flock(lock_file.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
    exe=Executor(api,enabled=enabled)
    while True:
        try:
            with sqlite3.connect(ROOT/'data/lab.sqlite',timeout=20) as db:
                decisions=[json.loads(r[0]) for r in db.execute('SELECT body FROM decisions ORDER BY rowid DESC LIMIT 200')]
            exe.tick(decisions)
            exe.snapshot['status']='OK'
        except Exception as exc:
            exe.snapshot.update(status='ERROR',error=str(exc) if isinstance(exc,(ValueError,ApiError)) else type(exc).__name__,checked_at=now().isoformat(),enabled=enabled)
            print('EXECUTOR ERROR '+exe.snapshot['error'],flush=True)
        tmp=ROOT/'data/paper-status.tmp';tmp.write_text(json.dumps(exe.snapshot),encoding='utf-8');tmp.replace(ROOT/'data/paper-status.json')
        time.sleep(10)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');p.add_argument('--probe');a=p.parse_args();run(a.check,a.probe)
