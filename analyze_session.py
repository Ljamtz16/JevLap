"""Export an auditable session report from saved data. No network or order calls."""
import argparse
from collections import Counter, defaultdict
from contextlib import closing
import csv
from datetime import date, datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path
import sqlite3
from urllib.parse import quote
import zipfile
from zoneinfo import ZoneInfo

NY = ZoneInfo('America/New_York')
ROOT = Path(__file__).resolve().parent
ARTIFACTS = ('FROZEN_HYPOTHESES_V02.json', 'HYPOTHESIS_DAILY_REPORT_V02.json',
             'PROSPECTIVE_HYPOTHESIS_REPORT_V02.json', 'PROSPECTIVE_SIZING_COMPARISON_V01.json',
             'PROSPECTIVE_RISK_GATE_V01.json', 'PROSPECTIVE_EXECUTION_GATE_V01.json',
             'SYSTEM_HEALTH_V01.json', 'research_dashboard_meta.json')
CSVS = ('data/processed/intraday/intraday_options_v2.csv',
        'data/processed/intraday/prospective_hypothesis_tracker_v02.csv',
        'data/processed/prospective/prospective_market_state_v1.csv')

def stamp(value):
    if not value: return None
    try:
        result = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return result if result.tzinfo else None
    except (TypeError, ValueError): return None

def in_session(value, day):
    parsed = stamp(value)
    return parsed is not None and parsed.astimezone(NY).date().isoformat() == day

def row_day(row):
    ts = row.get('captured_at_utc') or row.get('timestamp')
    parsed = stamp(ts)
    return parsed.astimezone(NY).date().isoformat() if parsed else row.get('decision_date') or row.get('market_date')

def number(value):
    try:
        import math
        result = float(value)
        return result if math.isfinite(result) else None
    except (ValueError, TypeError): return None

def stats(rows):
    closed = [r for r in rows if r.get('status') == 'CLOSED' and number(r.get('pnl')) is not None]
    pnls = [float(r['pnl']) for r in closed]
    return dict(records=len(rows), entries=sum(bool(r.get('contract')) for r in rows),
                statuses=dict(Counter(r.get('status', 'UNKNOWN') for r in rows)),
                closed=len(closed), wins=sum(x > 0 for x in pnls), losses=sum(x < 0 for x in pnls),
                win_rate_pct=round(100*sum(x > 0 for x in pnls)/len(pnls),2) if pnls else None,
                simulated_pnl_gross=round(sum(pnls),2) if pnls else None,
                exits=dict(Counter(r.get('reason', 'UNKNOWN') for r in closed)))

def first_activations(events, gap_minutes=6):
    """Diagnostic grouping only: no capital accounting or native episode-policy claims."""
    previous, first = {}, []
    for event in sorted(events, key=lambda r: stamp(r['timestamp'])):
        key = event['symbol'], event['hypothesis']
        ts = stamp(event['timestamp'])
        if key not in previous or ts-previous[key] > timedelta(minutes=gap_minutes): first.append(event)
        previous[key] = ts
    return first

def readonly_db(path):
    return sqlite3.connect('file:'+quote(str(Path(path).resolve()).replace('\\','/'), safe='/:')+'?mode=ro',uri=True,timeout=30)

def write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')

def write_csv(path, rows):
    if not rows:
        path.write_text('',encoding='utf-8');return
    fields = list(dict.fromkeys(k for r in rows for k in r))
    with path.open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields); writer.writeheader()
        writer.writerows({k:json.dumps(v, ensure_ascii=False) if isinstance(v,(dict,list)) else v for k,v in r.items()} for r in rows)

def jev_report(rows):
    result = dict(decisions=len(rows), unique_ids=len({r['id'] for r in rows}),
                  directions=dict(Counter(r['side'] for r in rows)), reasons=dict(Counter(r.get('reason') for r in rows)),
                  confidence_eligible=sum(r['side'] in ('CALL','PUT') and r['confidence'] >= r.get('config',{}).get('threshold',.75) for r in rows),
                  simulation=stats(rows), by_symbol={}, confidence_bands={}, comparison={})
    for symbol in sorted({r['symbol'] for r in rows}):
        subset=[r for r in rows if r['symbol']==symbol]
        result['by_symbol'][symbol]=dict(simulation=stats(subset), max_confidence=max(r['confidence'] for r in subset))
    for a,b in ((0,.7),(.7,.75),(.75,.8),(.8,.9),(.9,1.01)):
        result['confidence_bands'][f'{a*100:g}-{min(100,b*100):g}%']=stats([r for r in rows if a<=r['confidence']<b])
    for mode in ('PROSPECTIVE','RECONSTRUCTED'):
        subset=[r for r in rows if (r.get('comparison') or {}).get('signal',{}).get('evaluation_mode')==mode]
        matched=[r for r in subset if r.get('baseline') is not None]
        events=[]
        for r in subset:
            comp=r['comparison'];sig=comp['signal']
            for h in sig.get('hypotheses',[]):
                events.append({**(comp.get('system_simulation') or {}), 'timestamp':r['timestamp'], 'symbol':r['symbol'], 'hypothesis':h['id']})
                events[-1]['timestamp']=r['timestamp'];events[-1]['symbol']=r['symbol']
            for aux in comp.get('auxiliary_15m',[]):
                events.append(dict(aux,timestamp=r['timestamp'],symbol=r['symbol'],contract=aux.get('contract') or ('not_exported' if aux['status'] in ('OPEN','CLOSED') else None)))
        grouped={}
        for name in sorted({e['hypothesis'] for e in events}):
            hits=[e for e in events if e['hypothesis']==name]
            grouped[name]=dict(snapshot_simulations=stats(hits), first_activation_diagnostic=stats(first_activations(hits)),
                               note='Grouped by gaps >6 min, not a validated portfolio or native episode policy')
        result['comparison'][mode]=dict(records=len(subset), matched=len(matched),
            coverage_status=dict(Counter(r['comparison']['signal'].get('status') for r in subset)),
            groups=dict(Counter(r['comparison']['group'] for r in subset)),
            jev_on_matched=stats(matched), system_on_matched=stats([r['comparison']['system_simulation'] for r in matched]),
            hypotheses=grouped)
    result['without_comparison']=sum(not r.get('comparison') for r in rows)
    return result

def paper_report(lab, day):
    path=lab/'data/paper-status.json'
    summary={'source':'saved executor status and intents; no broker API reconciliation during export','available':False}
    if path.exists():
        raw=json.loads(path.read_text(encoding='utf-8'))
        keys=('checked_at','enabled','status','error','account_verified','mode','equity','buying_power','daily_equity_change','realized_pnl_gross','closed_trades','unrealized_pnl')
        summary.update(available=True,saved_status={k:raw.get(k) for k in keys}, positions=len(raw.get('positions',[])),open_orders=len(raw.get('open_orders',[])))
    orders=[];all_orders=[]
    dbpath=lab/'data/paper.sqlite'
    if dbpath.exists():
        with closing(readonly_db(dbpath)) as db:
            for cid,body,broker,state,created in db.execute('SELECT * FROM intents'):
                payload=json.loads(body);saved=json.loads(broker) if broker else {}
                order=dict(client_order_id=cid,created_at=created,local_state=state,
                           **{k:payload.get(k) for k in ('symbol','qty','side','position_intent','type','limit_price')},
                           broker_status=saved.get('status'),filled_qty=saved.get('filled_qty'),filled_avg_price=saved.get('filled_avg_price'),filled_at=saved.get('filled_at'))
                all_orders.append(order)
                if in_session(created,day) or in_session(saved.get('filled_at'),day):orders.append(order)
    trades=[]
    for entry in all_orders:
        if not entry['client_order_id'].startswith('jv-entry-') or number(entry['filled_qty'])!=1 or number(entry['filled_avg_price']) is None:continue
        prefix=entry['client_order_id'].replace('jv-entry-','jv-exit-')+'-'
        exits=[e for e in all_orders if e['client_order_id'].startswith(prefix) and number(e['filled_qty'])==1 and number(e['filled_avg_price']) is not None]
        if len(exits)>1:
            summary.setdefault('warnings',[]).append('Multiple saved exit fills for '+entry['client_order_id']);continue
        if exits and in_session(exits[0]['filled_at'],day):
            trades.append(dict(symbol=entry['symbol'],entry_at=entry['filled_at'],exit_at=exits[0]['filled_at'],
                               pnl_gross=round((float(exits[0]['filled_avg_price'])-float(entry['filled_avg_price']))*100,2)))
    summary.update(session_orders=len(orders),order_states=dict(Counter(o['local_state'] for o in orders)),
                   session_confirmed_closed_trades=trades,session_realized_pnl_gross=round(sum(t['pnl_gross'] for t in trades),2) if trades else None)
    return summary,orders

def run(lab,system,day,out):
    lab,system,out=Path(lab),Path(system),Path(out)
    out.mkdir(parents=True,exist_ok=True)
    report=dict(session_date_ny=day,generated_at_utc=datetime.now(timezone.utc).isoformat(),
                limitations=['Saved-data report, no new Jev calls or broker orders.',
                    'Snapshot simulations may overlap; summed hypothetical P&L is not a portfolio return.',
                    'Indicative quotes can be modified; simulation results do not establish executable profitability.',
                    'PROSPECTIVE and RECONSTRUCTED comparisons are reported separately.',
                    'Pending simulations and missing future horizons remain unknown; do not count as zero returns.',
                    'Saved paper status can be stale; broker fills are not refreshed by this export.'],warnings=[])
    rows=[]
    dbpath=lab/'data/lab.sqlite'
    if dbpath.exists():
        with closing(readonly_db(dbpath)) as db:
            db.execute('BEGIN')
            for raw, in db.execute("SELECT json_remove(body,'$.snapshot','$.request','$.raw') FROM decisions"):
                row=json.loads(raw)
                if in_session(row.get('timestamp'),day):rows.append(row)
    report['jev']=jev_report(rows)
    write_json(out/'jev_decisions.json',rows)
    write_csv(out/'jev_decisions.csv',rows)
    times=[r['timestamp'] for r in rows]
    report['jev'].update(first_capture=min(times,key=stamp) if times else None,last_capture=max(times,key=stamp) if times else None)
    paper,orders=paper_report(lab,day);report['jev_paper']=paper
    write_csv(out/'jev_paper_orders.csv',orders)
    system_report={'csv_sources':{},'artifacts':{},'session_daily_report':None,
                   'broker_history':'Not identified in repository sources; virtual accounts are simulations'}
    for relative in CSVS:
        path=system/relative
        if not path.exists():
            system_report['csv_sources'][relative]={'available':False};continue
        try:
            with path.open(encoding='utf-8-sig',newline='') as fh:all_rows=list(csv.DictReader(fh))
            selected=[r for r in all_rows if row_day(r)==day]
            system_report['csv_sources'][relative]={'available':True,'all_rows':len(all_rows),'session_rows':len(selected),
                'symbols':dict(Counter(r.get('symbol','SPY') for r in selected)), 'modified_at_utc':datetime.fromtimestamp(path.stat().st_mtime,timezone.utc).isoformat()}
            write_csv(out/path.name,selected)
        except (csv.Error,OSError,UnicodeError) as exc:
            system_report['csv_sources'][relative]={'error':type(exc).__name__}
    for name in ARTIFACTS:
        path=system/'artifacts/intraday'/name
        if not path.exists():system_report['artifacts'][name]={'available':False};continue
        content=path.read_bytes()
        try:obj=json.loads(content)
        except (ValueError,UnicodeError):system_report['artifacts'][name]={'error':'Invalid JSON'};continue
        info={'available':True,'sha256':hashlib.sha256(content).hexdigest(),
              'modified_at_utc':datetime.fromtimestamp(path.stat().st_mtime,timezone.utc).isoformat()}
        system_report['artifacts'][name]=info
        write_json(out/'options_artifacts'/name,obj)
        if name=='HYPOTHESIS_DAILY_REPORT_V02.json':
            current=obj.get('days',{}).get(day)
            system_report['session_daily_report']=current
            if current is None:report['warnings'].append('Options-System daily hypothesis report has no target session; post-close pipeline may not have finished.')
    for rel,info in system_report['csv_sources'].items():
        if not info.get('session_rows'):report['warnings'].append('No target-session rows in '+rel)
    snapshots=sorted((system/'data/raw/intraday').glob('intraday_options_'+day.replace('-','')+'T*.json'))
    system_report['raw_snapshot_inventory']={'files_named_for_utc_date':len(snapshots),'first_file':snapshots[0].name if snapshots else None,'last_file':snapshots[-1].name if snapshots else None,'note':'Filename inventory, not checksum validation or proof of capture completeness'}
    report['options_system']=system_report
    report['jev']['mature_horizon_counts']={str(h):sum((r.get('horizons') or {}).get(str(h)) is not None for r in rows) for h in (15,30,60)}
    write_json(out/'report.json',report)
    text=['# Session '+day, '', 'Saved data collected at '+report['generated_at_utc'],'',
          '## Jev',json.dumps(report['jev'],ensure_ascii=False,indent=2),'',
          '## Alpaca PAPER · saved records',json.dumps(paper,ensure_ascii=False,indent=2),'',
          '## Options-System',json.dumps(system_report,ensure_ascii=False,indent=2),'',
          '## Limitations',*['- '+x for x in report['limitations']+report['warnings']]]
    (out/'report.md').write_text('\n'.join(text),encoding='utf-8')
    archive=out.parent/(out.name+'.zip')
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(out.rglob('*')):
            if path.is_file():bundle.write(path,path.relative_to(out))
    print(json.dumps(dict(session=day,report=str(out/'report.json'),archive=str(archive),archive_bytes=archive.stat().st_size,
                         jev=report['jev'],jev_paper=paper,options_sources=system_report['csv_sources'],warnings=report['warnings']),ensure_ascii=False,indent=2))
    return report

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--date',default=datetime.now(NY).date().isoformat())
    parser.add_argument('--system-root',type=Path,default=Path.home()/'options-system')
    parser.add_argument('--out',type=Path)
    args=parser.parse_args();date.fromisoformat(args.date)
    run(ROOT,args.system_root,args.date,args.out or ROOT/'data/reports'/('session_'+args.date+'_'+datetime.now(timezone.utc).strftime('%H%M%S')))
