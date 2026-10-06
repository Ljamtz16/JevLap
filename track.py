"""Evaluate frozen decisions against accumulated observed option quotes."""
import json, sqlite3, sys
from datetime import datetime,timezone
from pathlib import Path
from engine import evaluate

if __name__ == '__main__':
    quotes=json.loads(Path(sys.argv[1]).read_text())
    dbpath=Path(__file__).resolve().parent/'data/lab.sqlite'
    count=0
    with sqlite3.connect(dbpath) as db:
        for ident,body in db.execute('SELECT id,body FROM decisions').fetchall():
            old=json.loads(body)
            decision={k:old[k] for k in ('side','confidence','probability','model','request','raw')}
            new=evaluate(old['snapshot'],decision,quotes,old['baseline'],old['config'],as_of=datetime.now(timezone.utc))
            for key in ('snapshot','decision_received_at','source_file','research_mode','dataset_policy'):
                if key in old:new[key]=old[key]
            db.execute("UPDATE decisions SET body=json_set(json(?),'$.comparison',json_extract(body,'$.comparison'),'$.baseline',json_extract(body,'$.baseline'),'$.agreement',json_extract(body,'$.agreement')) WHERE id=?",(json.dumps(new),ident))
            count+=1
    print(f'Evaluated {count} frozen decisions. No API requests or broker orders.')
