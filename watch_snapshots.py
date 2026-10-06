"""Independent consumer. Source snapshots are never modified."""
import argparse,json,sqlite3,time,os
from pathlib import Path
from datetime import datetime,timezone
from credentials import load
from snapshot_adapter import adapt
from engine import decide,evaluate
ROOT=Path(__file__).resolve().parent

def run(source,once=False):
    load()
    ROOT.joinpath('data').mkdir(exist_ok=True)
    with sqlite3.connect(ROOT/'data/lab.sqlite') as db:
        db.execute('CREATE TABLE IF NOT EXISTS decisions(id TEXT PRIMARY KEY, body TEXT NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS consumed(path TEXT PRIMARY KEY)')
        db.execute('CREATE TABLE IF NOT EXISTS quotes(symbol TEXT,timestamp TEXT,bid REAL,PRIMARY KEY(symbol,timestamp))')
    while True:
        for path in sorted(source.glob('intraday_options_*.json')):
            with sqlite3.connect(ROOT/'data/lab.sqlite') as db:
                if db.execute('SELECT 1 FROM consumed WHERE path=?',(str(path),)).fetchone():continue
                try:states,quotes,is_open=adapt(json.loads(path.read_text(encoding='utf-8')))
                except (ValueError,KeyError,TypeError):
                    print('Incomplete or unsupported snapshot:',path.name,flush=True);continue
                for q in quotes:db.execute('INSERT OR IGNORE INTO quotes VALUES(?,?,?)',(q['symbol'],q['timestamp'],q['bid']))
                for state in states:
                    age=(datetime.now(timezone.utc)-datetime.fromisoformat(state['timestamp'])).total_seconds()
                    # Never request retrospective decisions or enter on stale data.
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
                    db.execute('INSERT INTO decisions VALUES(?,?)',(ident,json.dumps(row)))
                for ident,raw in db.execute('SELECT id,body FROM decisions').fetchall():
                    old=json.loads(raw)
                    if not old.get('contract'):continue
                    observed=[dict(symbol=s,timestamp=t,bid=b) for s,t,b in db.execute('SELECT symbol,timestamp,bid FROM quotes WHERE symbol=? ORDER BY timestamp',(old['contract'],))]
                    decision={k:old[k] for k in ('side','confidence','probability','model','request','raw')}
                    new=evaluate(old['snapshot'],decision,observed,old['baseline'],old['config'])
                    for k in ('snapshot','decision_received_at','source_file','research_mode'):new[k]=old[k]
                    db.execute("UPDATE decisions SET body=json_set(json(?),'$.comparison',json_extract(body,'$.comparison'),'$.baseline',json_extract(body,'$.baseline'),'$.agreement',json_extract(body,'$.agreement')) WHERE id=?",(json.dumps(new),ident))
                db.execute('INSERT INTO consumed VALUES(?)',(str(path),))
            print('Consumed:',path.name,flush=True)
        if once:return
        time.sleep(10)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',required=True,type=Path);p.add_argument('--once',action='store_true');a=p.parse_args()
    if not a.source.is_dir():p.error('Source directory does not exist')
    run(a.source.resolve(),a.once)
