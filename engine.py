import json, math, os, urllib.request, hashlib
from datetime import datetime

SIDES = ('CALL', 'PUT', 'NO_TRADE')
CONFIG = dict(threshold=.75, tp=.20, sl=-.10, max_hold=60, max_spread=.15, quantity=1)

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

def evaluate(snapshot, decision, quotes, baseline=None, config=None):
    cfg = dict(CONFIG, **(config or {}))
    ts = datetime.fromisoformat(snapshot['timestamp'])
    if ts.tzinfo is None:
        raise ValueError('Timestamp requiere zona horaria')
    side = decision['side']
    if side not in SIDES or not 0 <= decision['confidence'] <= 1:
        raise ValueError('Decisión inválida')
    result = dict(id=hashlib.sha256((snapshot['timestamp']+snapshot['symbol']).encode()).hexdigest()[:20], timestamp=snapshot['timestamp'], symbol=snapshot['symbol'], **decision, baseline=baseline, agreement=None if baseline is None else side == baseline, config=cfg, status='SKIP', reason='', contract=None, entry=None, pnl=None, return_pct=None, horizons={}, mfe=None, mae=None)
    if side == 'NO_TRADE' or decision['confidence'] < cfg['threshold']:
        result['reason'] = 'Sin dirección / confianza insuficiente'
        return result
    valid=[]
    for c in snapshot.get('contracts', []):
        bid, ask = c.get('bid',0), c.get('ask',0)
        qts = datetime.fromisoformat(c['timestamp'])
        if c['side']==side and bid > 0 and ask >= bid and (ask-bid)/ask <= cfg['max_spread'] and 0 <= (ts-qts).total_seconds() <= 120 and c.get('volume',0) > 0:
            valid.append(c)
    if not valid:
        result['reason']='Sin contrato elegible'
        return result
    c=min(valid, key=lambda x: ((x['ask']-x['bid'])/x['ask'],x['symbol']))
    result.update(contract=c['symbol'], entry=c['ask'], status='OPEN', reason='Entrada simulada al ask')
    path=[]
    for q in quotes:
        qt=datetime.fromisoformat(q['timestamp'])
        minutes=(qt-ts).total_seconds()/60
        if q['symbol']==c['symbol'] and minutes>0 and q['bid']>0:
            path.append((minutes,q['bid']))
    path.sort()
    for h in (15,30,60):
        found=next(((m,p) for m,p in path if h<=m<=h+2),None)
        result['horizons'][str(h)]=None if not found else round((found[1]/c['ask']-1)*100,2)
    observed=[]
    for m,p in path:
        ret=p/c['ask']-1
        observed.append(ret)
        if ret>=cfg['tp'] or ret<=cfg['sl'] or m>=cfg['max_hold']:
            result.update(status='CLOSED',reason='TP' if ret>=cfg['tp'] else 'SL' if ret<=cfg['sl'] else 'TIME',pnl=round((p-c['ask'])*100*cfg['quantity'],2),return_pct=round(ret*100,2),exit=p,exit_minutes=m)
            break
    if observed:
        result.update(mfe=round(max(observed)*100,2),mae=round(min(observed)*100,2))
    return result
