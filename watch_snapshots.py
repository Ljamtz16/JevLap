"""Independent consumer. Source snapshots are never modified."""
import argparse,json,sqlite3,time,os
from pathlib import Path
from datetime import datetime,timezone
from credentials import load
from snapshot_adapter import adapt
from engine import decide,evaluate
from source_snapshots import snapshot_paths, allowed_symbols, COMMON_START_DATE
ROOT=Path(__file__).resolve().parent

def refresh_observations(db, as_of):
    count=0
    for ident,raw in db.execute("SELECT id,body FROM decisions WHERE json_extract(body,'$.status')='OPEN' AND json_extract(body,'$.contract') IS NOT NULL").fetchall():
        old=json.loads(raw)
        observed=[dict(symbol=s,timestamp=t,bid=b) for s,t,b in db.execute('SELECT symbol,timestamp,bid FROM quotes WHERE symbol=? ORDER BY timestamp',(old['contract'],))]
        decision={k:old[k] for k in ('side','confidence','probability','model','request','raw')}
        new=evaluate(old['snapshot'],decision,observed,old['baseline'],old['config'],as_of=as_of)
        for k in ('snapshot','decision_received_at','source_file','research_mode','dataset_policy'):
            if k in old:new[k]=old[k]
        if all(old.get(k)==v for k,v in new.items()):continue
        db.execute("UPDATE decisions SET body=json_set(json(?),'$.comparison',json_extract(body,'$.comparison'),'$.baseline',json_extract(body,'$.baseline'),'$.agreement',json_extract(body,'$.agreement')) WHERE id=?",(json.dumps(new),ident))
        count+=1
    return count

def run(source,once=False,canonical_source=None,start_date=COMMON_START_DATE):
    load()
    ROOT.joinpath('data').mkdir(exist_ok=True)
    dbpath=ROOT/'data/lab.sqlite'
    with sqlite3.connect(dbpath) as db:
        db.execute('CREATE TABLE IF NOT EXISTS decisions(id TEXT PRIMARY KEY, body TEXT NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS consumed(path TEXT PRIMARY KEY)')
        db.execute('CREATE TABLE IF NOT EXISTS quotes(symbol TEXT,timestamp TEXT,bid REAL,PRIMARY KEY(symbol,timestamp))')
        db.execute("CREATE INDEX IF NOT EXISTS decisions_status ON decisions(json_extract(body,'$.status'))")
    while True:
        with sqlite3.connect(dbpath,timeout=20) as db:
            consumed={row[0] for row in db.execute('SELECT path FROM consumed')}
            for path, source_kind in snapshot_paths(source,canonical_source):
                path_key=str(path)
                if path_key in consumed:continue
                try:
                    envelope=json.loads(path.read_text(encoding='utf-8'))
                    states,quotes,is_open=adapt(envelope)
                    permitted=allowed_symbols(envelope,source_kind,start_date)
                    states=[state for state in states if state['symbol'] in permitted]
                    contracts={c['symbol'] for state in states for c in state['contracts']}
                    quotes=[q for q in quotes if q['symbol'] in contracts]
                except (ValueError,KeyError,TypeError):
                    print('Incomplete or unsupported snapshot:',path.name,flush=True);continue
                decisions=[]
                for state in states:
                    age=(datetime.now(timezone.utc)-datetime.fromisoformat(state['timestamp'])).total_seconds()
                    if not is_open or not 0<=age<=120:continue
                    ident=__import__('hashlib').sha256((state['timestamp']+state['symbol']).encode()).hexdigest()[:20]
                    if db.execute('SELECT 1 FROM decisions WHERE id=?',(ident,)).fetchone():continue
                    try:decision=decide(state)
                    except Exception as exc:
                        print('Jev request failed:',type(exc).__name__,flush=True);continue
                    row=evaluate(state,decision,[]);row['snapshot']=state
                    row['decision_received_at']=datetime.now(timezone.utc).isoformat()
                    row['source_file']=path.name
                    row['research_mode']='snapshot_shadow'
                    row['dataset_policy']=source_kind
                    decisions.append((ident,json.dumps(row)))
                for q in quotes:db.execute('INSERT OR IGNORE INTO quotes VALUES(?,?,?)',(q['symbol'],q['timestamp'],q['bid']))
                if decisions:db.executemany('INSERT OR IGNORE INTO decisions VALUES(?,?)',decisions)
                db.execute('INSERT OR IGNORE INTO consumed VALUES(?)',(path_key,))
                db.commit()
                consumed.add(path_key)
                print('Consumed:',path.name,flush=True)
            refresh_observations(db,datetime.now(timezone.utc))
            db.commit()
        if once:return
        time.sleep(10)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',required=True,type=Path);p.add_argument('--once',action='store_true');p.add_argument('--canonical-source',type=Path);p.add_argument('--common-start-date',default=COMMON_START_DATE);a=p.parse_args()
    if not a.source.is_dir():p.error('Source directory does not exist')
    run(a.source.resolve(),a.once,a.canonical_source,a.common_start_date)
