import json, math, os, urllib.request, hashlib
from datetime import datetime
from session_policy import stamp, session_bounds, expiry_day, NY, SIMULATION_VERSION

SIDES = ('CALL', 'PUT', 'NO_TRADE')
CONFIG = dict(threshold=.75, tp=.20, sl=-.10, max_hold=60, max_spread=.15, quantity=1,
              contract_selection_version='executable_contract_v1', research_cash=1000.,
              premium_budget_fraction=.20, contract_selection_policy={})

def decide(state):
    # Explicit allowlist: never send baseline decisions or future quotes to Jev.
    clean = {k: state[k] for k in ('timestamp', 'symbol', 'features')}
    payload = dict(state=clean, model=os.getenv('JEV_MODEL', 'jev-1.13.0'), questions={
        'direction': dict(type='choice', instructions='Using only this market state, choose an experimental long option direction for the next 60 minutes. Abstain when evidence is insufficient. This is a research decision, not a guaranteed return.', criteria={
            'CALL': 'Bullish continuation supported by available features',
            'PUT': 'Bearish continuation supported by available features',
            'NO_TRADE': 'Insufficient evidence, mixed signals or unsuitable conditions'})})
    key = os.getenv('TYPESAFE_API_KEY')
    if not key:
        raise ValueError('Configura TYPESAFE_API_KEY en el servidor; no en el navegador.')
    req = urllib.request.Request('https://api.typesafe.ai/v1/systemone', json.dumps(payload).encode(), {'Authorization': 'Bearer '+key, 'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=25) as response:
        raw = json.load(response)
    answer = raw['answers']['direction']
    probs = answer['probabilities']
    if answer['choice'] not in SIDES or set(probs) != set(SIDES):
        raise ValueError('Respuesta Jev incompatible')
    if any(not math.isfinite(v) or not 0 <= v <= 1 for v in probs.values()) or abs(sum(probs.values())-1) > .01:
        raise ValueError('Probabilidades inválidas')
    conf = answer['confidence']
    if not math.isfinite(conf) or not 0 <= conf <= 1:
        raise ValueError('Confianza inválida')
    return dict(side=answer['choice'], confidence=conf, probability=probs[answer['choice']], model=raw['model'], request=payload, raw=raw)

def evaluate(snapshot, decision, quotes, baseline=None, config=None, as_of=None):
    cfg = dict(CONFIG, **(config or {}))
    if config is not None and 'contract_selection_version' not in config:
        cfg = {k:CONFIG[k] for k in ('threshold','tp','sl','max_hold','max_spread','quantity')}
        cfg.update(config)
    ts = stamp(snapshot['timestamp'])
    # Frozen old configurations retain their original selector; no silent historical rewrite.
    if ts.astimezone(NY).date().isoformat() < '2026-10-07' or (config is not None and 'contract_selection_version' not in config):
        if 'contract_selection_version' in cfg:
            cfg['contract_selection_version'] = 'legacy_spread_v1'
    session_start, session_close = session_bounds(snapshot)
    observed_at = stamp(as_of) if as_of is not None else max([ts] + [stamp(q['timestamp']) for q in quotes])
    side = decision['side']
    if side not in SIDES or not 0 <= decision['confidence'] <= 1:
        raise ValueError('Decisión inválida')
    result = dict(id=hashlib.sha256((snapshot['timestamp']+snapshot['symbol']).encode()).hexdigest()[:20], timestamp=snapshot['timestamp'], symbol=snapshot['symbol'], **decision, baseline=baseline, agreement=None if baseline is None else side == baseline, config=cfg, status='SKIP', reason='', contract=None, entry=None, pnl=None, return_pct=None, horizons={}, mfe=None, mae=None, simulation_version=SIMULATION_VERSION, session_date=ts.astimezone(NY).date().isoformat(), session_close_at_utc=session_close.isoformat(), entry_timestamp=None, exit_timestamp=None,strategy_mode='JEV_SHADOW',account_kind='SNAPSHOT_SIMULATION')
    if side == 'NO_TRADE' or decision['confidence'] < cfg['threshold']:
        result['reason'] = 'Sin dirección / confianza insuficiente'
        return result
    if not session_start <= ts < session_close:
        result['reason'] = 'OUTSIDE_SESSION'
        return result
    if cfg.get('contract_selection_version') == 'executable_contract_v1':
        from contract_selection import select_contract
        selection = select_contract(snapshot.get('contracts', []), side, ts,
                                    snapshot.get('features', {}).get('spot'), cfg['research_cash'],
                                    cfg['premium_budget_fraction'], quantity=cfg['quantity'],
                                    underlying=snapshot['symbol'],
                                    policy=dict(cfg['contract_selection_policy'], max_spread_pct=cfg['max_spread']))
        result['contract_selection'] = selection
        c = selection['selected']
        if not c:
            result['reason'] = selection['reason']
            return result
    else:
        valid=[]
        for c in snapshot.get('contracts', []):
            bid, ask = c.get('bid',0), c.get('ask',0)
            qts = stamp(c['timestamp'])
            if c['side']==side and qts >= session_start and (expiry_day(c['symbol']) is None or expiry_day(c['symbol']) >= ts.astimezone(NY).date()) and bid > 0 and ask >= bid and (ask-bid)/ask <= cfg['max_spread'] and 0 <= (ts-qts).total_seconds() <= 120 and c.get('volume',0) > 0:
                valid.append(c)
        if not valid:
            result['reason']='Sin contrato elegible'
            return result
        c=min(valid, key=lambda x: ((x['ask']-x['bid'])/x['ask'],x['symbol']))
    result.update(contract=c['symbol'], entry=c['ask'], status='OPEN', reason='Entrada simulada al ask',
                  entry_timestamp=ts.isoformat(), entry_quote_timestamp=c['timestamp'],
                  entry_bid=c['bid'], entry_ask=c['ask'], quantity=cfg['quantity'],
                  capital_required=c['ask'] * 100 * cfg['quantity'],
                  strategy_mode='JEV_SHADOW', account_kind='SNAPSHOT_SIMULATION')
    path=[]
    for q in quotes:
        qt=stamp(q['timestamp'])
        minutes=(qt-ts).total_seconds()/60
        if q['symbol']==c['symbol'] and ts < qt <= min(session_close, observed_at) and q['bid']>0:
            path.append((minutes,q['bid'],qt))
    path.sort(key=lambda item: item[0])
    for h in (15,30,60):
        found=next(((m,p) for m,p,_ in path if h<=m<=h+2),None)
        result['horizons'][str(h)]=None if not found else round((found[1]/c['ask']-1)*100,2)
    observed=[]
    def close_at(price, qt, reason):
        ret=price/c['ask']-1
        result.update(status='CLOSED',reason=reason,pnl=round((price-c['ask'])*100*cfg['quantity'],2),
                      return_pct=round(ret*100,2),exit=price,exit_minutes=(qt-ts).total_seconds()/60,
                      exit_timestamp=qt.isoformat())
    for m,p,qt in path:
        ret=p/c['ask']-1
        observed.append(ret)
        if ret>=cfg['tp'] or ret<=cfg['sl'] or m>=cfg['max_hold']:
            close_at(p,qt,'TP' if ret>=cfg['tp'] else 'SL' if ret<=cfg['sl'] else 'TIME')
            break
    if result['status']=='OPEN' and observed_at >= session_close:
        last=path[-1] if path else None
        if last and (session_close-last[2]).total_seconds() <= cfg.get('close_quote_max_age_seconds',120):
            close_at(last[1],last[2],'SESSION_CLOSE')
        else:
            expired=expiry_day(c['symbol'])
            result.update(status='EXPIRED' if expired and expired<=ts.astimezone(NY).date() else 'INCOMPLETE',
                          reason='EXPIRY_NO_VALID_CLOSE_QUOTE' if expired and expired<=ts.astimezone(NY).date() else 'SESSION_CLOSE_NO_VALID_QUOTE')
    if observed:
        result.update(mfe=round(max(observed)*100,2),mae=round(min(observed)*100,2))
    return result
