"""Read-only causal replay of Options-System frozen hypotheses; no network/orders."""
import argparse
from contextlib import closing
from datetime import datetime, timezone, date
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import time
from engine import evaluate
from snapshot_adapter import adapt, intraday_view
from source_snapshots import snapshot_paths, allowed_symbols, COMMON_START_DATE

ROOT = Path(__file__).resolve().parent
FIELDS = ('baseline', 'agreement', 'comparison')

def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

class Comparator:
    def __init__(self, system_root, db_path=None):
        self.system_root = Path(system_root)
        self.db_path = Path(db_path or ROOT/'data/lab.sqlite')
        paths = [self.system_root/'artifacts/intraday/FROZEN_HYPOTHESES_V02.json',
                 self.system_root/'src/options_system/chain_features.py',
                 self.system_root/'src/options_system/prospective_hypothesis_tracker.py']
        self.version = hashlib.sha256(b''.join(p.read_bytes() for p in paths)).hexdigest()
        self.meta = json.loads(paths[0].read_text(encoding='utf-8'))
        self.hypotheses = self.meta['hypotheses']
        self.chain = load_module(paths[1], 'comparison_chain').extract_chain_features
        self.active = load_module(paths[2], 'comparison_rules').hypothesis_active
        self.previous = {}
        with closing(sqlite3.connect(self.db_path, timeout=30)) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS comparison_signals(timestamp TEXT,symbol TEXT,body TEXT,PRIMARY KEY(timestamp,symbol))')
            db.execute('CREATE TABLE IF NOT EXISTS comparison_consumed(path TEXT PRIMARY KEY)')
            db.execute('CREATE TABLE IF NOT EXISTS comparison_pending(id TEXT PRIMARY KEY)')
            db.execute('CREATE TABLE IF NOT EXISTS comparison_runtime(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
            if db.execute('SELECT COUNT(*) FROM comparison_consumed').fetchone()[0] == 0 and db.execute('SELECT COUNT(*) FROM comparison_signals').fetchone()[0] > 0:
                known = {r[0] for r in db.execute("SELECT DISTINCT json_extract(body,'$.source_file') FROM comparison_signals WHERE json_extract(body,'$.source_file') IS NOT NULL")}
                source = self.system_root/'data/raw/intraday'
                for path, _ in snapshot_paths(source, None):
                    if path.name in known:
                        db.execute('INSERT OR IGNORE INTO comparison_consumed VALUES(?)', (str(path),))
            latest = db.execute('SELECT c.symbol,c.body FROM comparison_signals c JOIN (SELECT symbol,MAX(timestamp) AS ts FROM comparison_signals GROUP BY symbol) m ON c.symbol=m.symbol AND c.timestamp=m.ts').fetchall()
            self.previous = {symbol: json.loads(body) for symbol, body in latest}
            saved = db.execute("SELECT value FROM comparison_runtime WHERE key='last_decision_rowid'").fetchone()
            if saved is None:
                # One-time migration: preserve any unfinished pre-runtime work, then never full-scan again.
                self.last_decision_rowid = int(db.execute('SELECT COALESCE(MAX(rowid),0) FROM decisions').fetchone()[0])
                for ident, body in db.execute('SELECT id,body FROM decisions'):
                    try:
                        row = json.loads(body)
                    except (ValueError, TypeError):
                        continue
                    cmp = row.get('comparison') or {}
                    sim = cmp.get('system_simulation') or {}
                    aux = cmp.get('auxiliary_15m') or []
                    if not cmp or row.get('status') == 'OPEN' or sim.get('status') == 'OPEN' or any((x or {}).get('status') == 'OPEN' for x in aux):
                        db.execute('INSERT OR IGNORE INTO comparison_pending VALUES(?)', (ident,))
                db.execute("INSERT INTO comparison_runtime VALUES('last_decision_rowid',?)", (str(self.last_decision_rowid),))
            else:
                self.last_decision_rowid = int(saved[0])

    def signal(self, envelope, symbol, previous=None, now=None):
        now = now or datetime.now(timezone.utc)
        ts = envelope['captured_at_utc']
        payload = intraday_view(envelope['payload'])
        md = payload['market_date']
        eligible = [h for h in self.hypotheses if symbol in h.get('symbol_scope', [])]
        out = dict(timestamp=ts, symbol=symbol, market_date=md, snapshot_sha256=envelope['sha256'],
                   policy_sha256=self.version, evaluated_at=now.isoformat(),
                   evaluation_mode='PROSPECTIVE' if 0 <= (now-datetime.fromisoformat(ts)).total_seconds() <= 120 else 'RECONSTRUCTED',
                   source='Options-System frozen hypotheses V02', horizon_min=60,
                   status='OUT_OF_SCOPE', side=None, hypotheses=[], auxiliary_15m=[], features={})
        if not eligible: return out
        if date.fromisoformat(md) <= date.fromisoformat(self.meta['frozen_at']):
            out['status'] = 'PRE_FREEZE'; return out
        rec = payload['symbols'][symbol]
        captured = datetime.fromisoformat(ts)
        chain = {'snapshots': {}}
        for name, option in (rec.get('option_snapshot') or {}).get('snapshots', {}).items():
            item = dict(option)
            # Do not use records dated after the capture, even during replay.
            for field in ('latestQuote', 'dailyBar'):
                stamp = (item.get(field) or {}).get('t')
                if stamp and datetime.fromisoformat(stamp.replace('Z', '+00:00')) > captured:
                    item.pop(field, None)
            chain['snapshots'][name] = item
        features = self.chain(chain, float(rec['spot']), date.fromisoformat(md))
        context = (payload.get('global_context') or {}).get('cross_market') or {}
        for key in ('spy_from_open', 'iwm_from_open', 'qqq_from_open'):
            features[key] = context.get(key)
        if previous and previous.get('market_date') == md and datetime.fromisoformat(previous['timestamp']) < captured:
            for key in ('atm_iv', 'put_call_iv_skew', 'put_call_volume_ratio_1pct'):
                a, b = features.get(key), previous.get('features', {}).get(key)
                features['d_'+key+'_prev'] = a-b if a is not None and b is not None else None
        out['features'] = features
        missing = []
        legacy = {'d_atm_iv_prev_gt':'d_atm_iv_prev', 'd_put_call_iv_skew_prev_lt':'d_put_call_iv_skew_prev',
                  'd_put_call_volume_ratio_1pct_prev_gt':'d_put_call_volume_ratio_1pct_prev',
                  'put_call_iv_skew_gt':'put_call_iv_skew', 'put_call_volume_ratio_1pct_lt':'put_call_volume_ratio_1pct'}
        for h in eligible:
            fields = [r['feature'] for r in h['rules']] if isinstance(h['rules'], list) else [legacy[k] for k in h['rules']]
            ready = all(features.get(f) is not None for f in fields)
            if h['horizon_min'] == 60 and not ready: missing.append(h['id'])
            if ready and self.active(h, features):
                target = 'hypotheses' if h['horizon_min'] == 60 else 'auxiliary_15m'
                out[target].append(dict(id=h['id'], side=h['side'].upper(), horizon_min=h['horizon_min']))
        sides = {h['side'] for h in out['hypotheses']}
        if len(sides) > 1: out['status'] = 'CONFLICT'
        elif sides: out.update(status='READY', side=next(iter(sides)))
        elif missing: out['status'] = 'MISSING_FEATURES'
        else: out.update(status='READY', side='NO_TRADE')
        out['missing_hypotheses'] = missing
        return out

    def scan(self, source, canonical_source=None, start_date=COMMON_START_DATE):
        previous = dict(self.previous)
        with closing(sqlite3.connect(self.db_path, timeout=30)) as db, db:
            consumed = {row[0] for row in db.execute('SELECT path FROM comparison_consumed')}
            for path, source_kind in snapshot_paths(source, canonical_source):
                path_key = str(path)
                if path_key in consumed:
                    continue
                try:
                    envelope = json.loads(path.read_text(encoding='utf-8'))
                    states, _, _ = adapt(envelope)
                    permitted = allowed_symbols(envelope, source_kind, start_date)
                    states = [state for state in states if state['symbol'] in permitted]
                    for state in states:
                        symbol, ts = state['symbol'], state['timestamp']
                        found = db.execute('SELECT body FROM comparison_signals WHERE timestamp=? AND symbol=?', (ts, symbol)).fetchone()
                        if found:
                            signal = json.loads(found[0])
                        else:
                            signal = self.signal(envelope, symbol, previous.get(symbol))
                            signal['source_file'] = path.name
                            signal['dataset_policy'] = source_kind
                            db.execute('INSERT INTO comparison_signals VALUES(?,?,?)', (ts, symbol, json.dumps(signal)))
                        previous[symbol] = signal
                    db.execute('INSERT OR IGNORE INTO comparison_consumed VALUES(?)', (path_key,))
                    consumed.add(path_key)
                except (ValueError, KeyError, TypeError, OSError) as exc:
                    print('Comparison skipped snapshot:', path.name, type(exc).__name__, flush=True)
            self.previous = previous

    def update(self):
        count = 0
        with closing(sqlite3.connect(self.db_path, timeout=30)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            newest = self.last_decision_rowid
            for rowid, ident in db.execute('SELECT rowid,id FROM decisions WHERE rowid>? ORDER BY rowid', (self.last_decision_rowid,)):
                newest = rowid
                db.execute('INSERT OR IGNORE INTO comparison_pending VALUES(?)', (ident,))
            if newest != self.last_decision_rowid:
                self.last_decision_rowid = newest
                db.execute("INSERT OR REPLACE INTO comparison_runtime VALUES('last_decision_rowid',?)", (str(newest),))
            records = db.execute("SELECT d.id,d.body,s.body FROM comparison_pending p JOIN decisions d ON d.id=p.id JOIN comparison_signals s ON json_extract(d.body,'$.timestamp')=s.timestamp AND json_extract(d.body,'$.symbol')=s.symbol").fetchall()
            for ident, body, raw_signal in records:
                row, signal = json.loads(body), json.loads(raw_signal)
                if (row.get('comparison') or {}).get('signal', {}).get('policy_sha256') not in (None, signal['policy_sha256']):
                    db.execute('DELETE FROM comparison_pending WHERE id=?',(ident,)); continue
                snapshot = row.get('snapshot')
                if not snapshot:
                    db.execute('DELETE FROM comparison_pending WHERE id=?',(ident,)); continue
                if (row.get('comparison') or {}).get('signal', {}).get('snapshot_sha256') not in (None, signal['snapshot_sha256']):
                    db.execute('DELETE FROM comparison_pending WHERE id=?',(ident,)); continue
                if row.get('source_file') != signal.get('source_file'):
                    db.execute('DELETE FROM comparison_pending WHERE id=?',(ident,)); continue
                if snapshot.get('snapshot_sha256') not in (None,signal['snapshot_sha256']):
                    db.execute('DELETE FROM comparison_pending WHERE id=?',(ident,)); continue
                if signal.get('dataset_policy')=='SPY_PROSPECTIVE_CANONICAL_V1' and snapshot.get('snapshot_sha256')!=signal['snapshot_sha256']:
                    db.execute('DELETE FROM comparison_pending WHERE id=?',(ident,)); continue
                def simulate(decision, config):
                    first = evaluate(snapshot, decision, [], config=config)
                    if not first.get('contract'): return first
                    observed = [dict(symbol=s, timestamp=t, bid=b) for s,t,b in db.execute('SELECT symbol,timestamp,bid FROM quotes WHERE symbol=? ORDER BY timestamp', (first['contract'],))]
                    return evaluate(snapshot, decision, observed, config=config, as_of=datetime.now(timezone.utc))
                baseline = signal['side'] if signal['status'] == 'READY' else None
                sim = None
                if baseline is not None:
                    decision = dict(side=baseline, confidence=1, probability=None, model='frozen_rules')
                    sim = simulate(decision, row['config'])
                    sim['strategy_mode'] = 'COMPARATOR_SHADOW'
                    sim = {k:v for k,v in sim.items() if k not in ('request','raw','snapshot')}
                jev_side = row['side'] if row['confidence'] >= row['config']['threshold'] else 'NO_TRADE'
                group = 'Sin comparar'
                if baseline is not None:
                    if baseline == jev_side == 'NO_TRADE': group = 'Ambos abstienen'
                    elif baseline == 'NO_TRADE': group = 'Jev solo'
                    elif jev_side == 'NO_TRADE': group = 'Sistema solo'
                    elif baseline == jev_side: group = 'Coinciden'
                    else: group = 'Direcciones opuestas'
                aux = []
                for h in signal['auxiliary_15m']:
                    result = simulate(dict(side=h['side'], confidence=1, probability=None, model=h['id']), dict(row['config'], max_hold=15, tp=.10, sl=-.10))
                    aux.append(dict(result,hypothesis=h['id'],horizon_min=15,strategy_mode='COMPARATOR_H02_SHADOW',account_kind='SNAPSHOT_SIMULATION'))
                comparison = dict(signal=signal, group=group, jev_effective_side=jev_side, system_simulation=sim, auxiliary_15m=aux)
                agreement = None if baseline is None else baseline == jev_side
                final = row.get('status') != 'OPEN' and not (sim or {}).get('status') == 'OPEN' and not any((x or {}).get('status') == 'OPEN' for x in aux)
                if row.get('comparison') != comparison or row.get('baseline') != baseline or row.get('agreement') != agreement:
                    db.execute("UPDATE decisions SET body=json_set(body,'$.baseline',json(?),'$.agreement',json(?),'$.comparison',json(?)) WHERE id=?", (json.dumps(baseline), json.dumps(agreement), json.dumps(comparison), ident))
                    count += 1
                if final:
                    db.execute('DELETE FROM comparison_pending WHERE id=?',(ident,))
        return count

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--system-root', type=Path, default=Path.home()/'options-system')
    p.add_argument('--once', action='store_true')
    p.add_argument('--canonical-source',type=Path)
    p.add_argument('--common-start-date',default=COMMON_START_DATE)
    a = p.parse_args()
    comp = Comparator(a.system_root)
    while True:
        comp.scan(a.system_root/'data/raw/intraday',a.canonical_source,a.common_start_date)
        print('Comparison rows:', comp.update(), flush=True)
        if a.once: break
        time.sleep(20)
