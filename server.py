from contextlib import closing
import json, os, sqlite3
from urllib.parse import urlsplit, parse_qs
from pathlib import Path
from http.server import ThreadingHTTPServer as HTTPServer, BaseHTTPRequestHandler
from engine import CONFIG, decide, evaluate

from credentials import load as load_credentials
load_credentials()

ROOT=Path(__file__).resolve().parent
DB=ROOT/'data'/'lab.sqlite'
SYSTEM_ROOT=Path(os.getenv('OPTIONS_SYSTEM_ROOT',str(ROOT.parent/'options-system')))
DB.parent.mkdir(exist_ok=True)
with closing(sqlite3.connect(DB)) as db, db:
    db.execute('CREATE TABLE IF NOT EXISTS decisions(id TEXT PRIMARY KEY, body TEXT NOT NULL)')

class Handler(BaseHTTPRequestHandler):
    def send(self, value, code=200):
        body=json.dumps(value, allow_nan=False).encode()
        self.send_response(code); self.send_header('Content-Type','application/json'); self.send_header('Cache-Control','no-store'); self.end_headers(); self.wfile.write(body)
    def do_GET(self):
        if self.path=='/api/local-paper':
            path=SYSTEM_ROOT/'artifacts/intraday/PAPER_TRADING_LIVE_STATE_V01.json'
            value=json.loads(path.read_text()) if path.exists() else {'status':'NOT_STARTED'}
            return self.send(dict(state=value,mode='LIVE_PAPER',account_kind='LOCAL_SIMULATION'))
        if self.path=='/api/analysis':
            def report(path):
                return json.loads(path.read_text()) if path.exists() else {'status':'NOT_GENERATED','auto_apply':False}
            return self.send(dict(calibration=report(ROOT/'data/calibration-analysis.json'),
                                  entry_controls=report(SYSTEM_ROOT/'artifacts/intraday/ENTRY_CONTROLS_ANALYSIS_V01.json')))
        if self.path=='/api/paper':
            status_path=ROOT/'data/paper-status.json'
            status=json.loads(status_path.read_text(encoding='utf-8')) if status_path.exists() else {'enabled':False,'status':'NOT_STARTED'}
            status['quote_feed']=os.getenv('JEV_OPTIONS_FEED','opra')
            history=[]
            paper_db=ROOT/'data/paper.sqlite'
            if paper_db.exists():
                with closing(sqlite3.connect(paper_db,timeout=20)) as db, db:
                    for cid,body,broker,state,created in db.execute('SELECT * FROM intents ORDER BY created DESC LIMIT 100'):
                        history.append(dict(client_order_id=cid,request=json.loads(body),broker=None if not broker else json.loads(broker),state=state,created_at=created))
            status.update(mode='ALPACA_PAPER',account_kind='BROKER_PAPER')
            return self.send(dict(status=status,orders=history))
        if urlsplit(self.path).path=='/api/decision':
            ident=parse_qs(urlsplit(self.path).query).get('id',[''])[0]
            with closing(sqlite3.connect(DB,timeout=20)) as db, db:
                row=db.execute('SELECT body FROM decisions WHERE id=?',(ident,)).fetchone()
            return self.send(json.loads(row[0]) if row else {'error':'Decision not found'},200 if row else 404)
        if self.path=='/api/results':
            with closing(sqlite3.connect(DB,timeout=20)) as db, db:
                # Full inputs and provider responses remain available on demand.
                rows=[json.loads(r[0]) for r in db.execute("SELECT json_remove(body,'$.snapshot','$.request','$.raw') FROM decisions ORDER BY rowid DESC")]
            return self.send(dict(rows=rows, jev_configured=bool(os.getenv('TYPESAFE_API_KEY')),broker_mode='ALPACA_PAPER', trading_threshold=CONFIG['threshold']))
        if self.path in ('/','/index.html'):
            self.send_response(200); self.send_header('Content-Type','text/html; charset=utf-8'); self.send_header('Cache-Control','no-store'); self.end_headers(); self.wfile.write((ROOT/'web/index.html').read_bytes()); return
        self.send({'error':'Not found'},404)
    def do_POST(self):
        # Local-only API, no cross-origin writes; keys stay in environment.
        if self.headers.get('Origin') and self.headers['Origin'] != 'http://'+self.headers.get('Host',''):
            return self.send({'error':'Origen rechazado'},403)
        try:
            length=int(self.headers.get('Content-Length',0))
            if not 0 < length <= 2000000:
                raise ValueError('Archivo demasiado grande o vacío')
            body=json.loads(self.rfile.read(length))
            if self.path=='/api/evaluate':
                snapshot=body['snapshot']
                # A persisted decision is immutable; replay only updates observations.
                from hashlib import sha256
                ident=sha256((snapshot['timestamp']+snapshot['symbol']).encode()).hexdigest()[:20]
                with closing(sqlite3.connect(DB)) as db, db:
                    old=db.execute('SELECT body FROM decisions WHERE id=?',(ident,)).fetchone()
                    if old: return self.send(json.loads(old[0]))
                decision=decide(snapshot)
                row=evaluate(snapshot,decision,[],body.get('baseline'))
                row['snapshot']=snapshot
                with closing(sqlite3.connect(DB)) as db, db:
                    db.execute('INSERT INTO decisions VALUES(?,?)',(row['id'],json.dumps(row)))
                return self.send(row)
            raise ValueError('Ruta desconocida')
        except Exception as exc:
            # Avoid exposing provider response / credential-bearing request internals.
            self.send({'error': str(exc) if isinstance(exc,ValueError) else type(exc).__name__+': solicitud fallida'},400)

if __name__=='__main__':
    import ipaddress, threading
    port=int(os.getenv('PORT','8787'))
    tail_ip=os.getenv('JEV_TAILSCALE_IP','').strip()
    if tail_ip:
        address=ipaddress.ip_address(tail_ip)
        if address not in ipaddress.ip_network('100.64.0.0/10'):
            raise ValueError('JEV_TAILSCALE_IP must be a Tailscale IPv4 address')
        private_server=HTTPServer((tail_ip,port),Handler)
        threading.Thread(target=private_server.serve_forever,daemon=True).start()
        print(f'Jev Lab Tailscale: http://{tail_ip}:{port}',flush=True)
    print(f'Jev Lab local: http://127.0.0.1:{port} — estado del ejecutor en /api/paper',flush=True)
    HTTPServer(('127.0.0.1',port),Handler).serve_forever()
