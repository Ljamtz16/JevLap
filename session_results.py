"""Session-scoped, paginated reads. No model or execution policy changes."""
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo
import json

NY=ZoneInfo('America/New_York')


def today():
    return datetime.now(NY).date().isoformat()


def day_bounds(day):
    value=date.fromisoformat(day)
    start=datetime.combine(value,time.min,NY)
    end=datetime.combine(value+timedelta(days=1),time.min,NY)
    return start.astimezone(timezone.utc).isoformat(),end.astimezone(timezone.utc).isoformat()


def index_results(db):
    # A compact projection keeps polling and history pages off large snapshots.
    db.execute('CREATE TABLE IF NOT EXISTS decisions_dashboard(id TEXT PRIMARY KEY,body TEXT NOT NULL)')
    for operation in ('INSERT','UPDATE'):
        db.execute("CREATE TRIGGER IF NOT EXISTS dashboard_after_"+operation.lower()+" AFTER "+operation+" ON decisions BEGIN INSERT OR REPLACE INTO decisions_dashboard(id,body) VALUES(new.id,json_remove(new.body,'$.snapshot','$.request','$.raw')); END")
    db.execute('CREATE TRIGGER IF NOT EXISTS dashboard_after_delete AFTER DELETE ON decisions BEGIN DELETE FROM decisions_dashboard WHERE id=old.id; END')
    db.execute("INSERT OR IGNORE INTO decisions_dashboard(id,body) SELECT id,json_remove(body,'$.snapshot','$.request','$.raw') FROM decisions WHERE NOT EXISTS(SELECT 1 FROM decisions_dashboard d WHERE d.id=decisions.id)")
    db.execute("CREATE INDEX IF NOT EXISTS dashboard_session_symbol ON decisions_dashboard(json_extract(body,'$.session_date'),json_extract(body,'$.symbol'))")
    db.execute("CREATE INDEX IF NOT EXISTS dashboard_timestamp ON decisions_dashboard(julianday(json_extract(body,'$.timestamp')))")


def where_day(query):
    day=(query.get('day') or [today()])[0]
    if day in ('today','__today'):day=today()
    if day=='all':return day,'1',[]
    start,end=day_bounds(day)
    sql="(json_extract(body,'$.session_date')=? OR (json_extract(body,'$.session_date') IS NULL AND julianday(json_extract(body,'$.timestamp'))>=julianday(?) AND julianday(json_extract(body,'$.timestamp'))<julianday(?)))"
    return day,sql,[day,start,end]


def results(db,query):
    day,scope,args=where_day(query)
    clauses=[scope]
    for key in ('symbol','side'):
        value=(query.get(key) or [''])[0]
        if value:
            clauses.append("json_extract(body,'$."+key+"')=?");args.append(value)
    confidence=float((query.get('confidence') or [0])[0])
    if not 0<=confidence<=1:raise ValueError('Confianza fuera de rango')
    clauses.append("coalesce(json_extract(body,'$.confidence'),0)>=?");args.append(confidence)
    where=' AND '.join(clauses)
    limit=max(1,min(500,int((query.get('limit') or [250])[0])))
    offset=max(0,int((query.get('offset') or [0])[0]))
    summary=db.execute("SELECT count(*),sum(json_extract(body,'$.status')='CLOSED'),coalesce(sum(CASE WHEN json_extract(body,'$.status')='CLOSED' THEN json_extract(body,'$.pnl') ELSE 0 END),0),sum(json_extract(body,'$.status')='CLOSED' AND json_extract(body,'$.pnl')>0) FROM decisions_dashboard WHERE "+where,args).fetchone()
    rows=[json.loads(row[0]) for row in db.execute("SELECT json_remove(body,'$.snapshot','$.request','$.raw') FROM decisions_dashboard WHERE "+where+" ORDER BY rowid DESC LIMIT ? OFFSET ?",[*args,limit,offset])]
    _,symbol_scope,symbol_args=where_day(query)
    symbols=[r[0] for r in db.execute("SELECT DISTINCT json_extract(body,'$.symbol') FROM decisions_dashboard WHERE "+symbol_scope+" ORDER BY 1",symbol_args) if r[0]]
    return dict(rows=rows,session_date=day,total=summary[0],limit=limit,offset=offset,
                summary=dict(decisions=summary[0],closed=summary[1] or 0,pnl=summary[2],wins=summary[3] or 0),symbols=symbols)


def sessions(db):
    values=Counter({r[0]:r[1] for r in db.execute("SELECT json_extract(body,'$.session_date'),count(*) FROM decisions_dashboard WHERE json_extract(body,'$.session_date') IS NOT NULL GROUP BY json_extract(body,'$.session_date')")})
    for row in db.execute("SELECT json_extract(body,'$.timestamp') FROM decisions_dashboard WHERE json_extract(body,'$.session_date') IS NULL"):
        try:values[datetime.fromisoformat(row[0].replace('Z','+00:00')).astimezone(NY).date().isoformat()]+=1
        except (TypeError,ValueError):pass
    values.setdefault(today(),0)
    return dict(today=today(),sessions=[dict(day=k,decisions=v) for k,v in sorted(values.items(),reverse=True)])


def scope_local_state(state,query):
    day=(query.get('day') or [today()])[0]
    if day=='all':return state
    if day in ('today','__today'):day=today()
    day_bounds(day)
    def belongs(row):
        stamp=row.get('entry_time') or row.get('signal_time')
        if not stamp:return False
        return datetime.fromisoformat(stamp.replace('Z','+00:00')).astimezone(NY).date().isoformat()==day
    value=dict(state)
    value['live_ledger']=[r for r in state.get('live_ledger',[]) if belongs(r)]
    value['session_date']=day
    value['session_realized_net_pnl']=sum(float(r.get('net_pnl') or 0) for r in value['live_ledger'] if r.get('status')=='CLOSED')
    return value
