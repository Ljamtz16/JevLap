import json, os, sqlite3
from pathlib import Path
from http.server import ThreadingHTTPServer as HTTPServer, BaseHTTPRequestHandler
from engine import decide, evaluate

from credentials import load as load_credentials
load_credentials()

ROOT=Path(__file__).resolve().parent
DB=ROOT/'data'/'lab.sqlite'
DB.parent.mkdir(exist_ok=True)
with sqlite3.connect(DB) as db:
    db.execute('CREATE TABLE IF NOT EXISTS decisions(id TEXT PRIMARY KEY, body TEXT NOT NULL)')

class Handler(BaseHTTPRequestHandler):
    def send(self, value, code=200):
        body=json.dumps(value, allow_nan=False).encode()
        self.send_response(code); self.send_header('Content-Type','application/json'); self.end_headers(); self.wfile.write(body)
    def do_GET(self):
        if self.path=='/api/results':
            with sqlite3.connect(DB) as db:
                rows=[json.loads(r[0]) for r in db.execute('SELECT body FROM decisions ORDER BY rowid DESC')]
            return self.send(dict(rows=rows, jev_configured=bool(os.getenv('TYPESAFE_API_KEY')),broker='DISABLED'))
        if self.path in ('/','/index.html'):
            self.send_response(200); self.send_header('Content-Type','text/html; charset=utf-8'); self.end_headers(); self.wfile.write((ROOT/'web/index.html').read_bytes()); return
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
                with sqlite3.connect(DB) as db:
                    old=db.execute('SELECT body FROM decisions WHERE id=?',(ident,)).fetchone()
                    if old: return self.send(json.loads(old[0]))
                decision=decide(snapshot)
                row=evaluate(snapshot,decision,[],body.get('baseline'))
                row['snapshot']=snapshot
                with sqlite3.connect(DB) as db:
                    db.execute('INSERT INTO decisions VALUES(?,?)',(row['id'],json.dumps(row)))
                return self.send(row)
            raise ValueError('Ruta desconocida')
        except Exception as exc:
            # Avoid exposing provider response / credential-bearing request internals.
            self.send({'error': str(exc) if isinstance(exc,ValueError) else type(exc).__name__+': solicitud fallida'},400)

if __name__=='__main__':
    print('Jev Lab: http://127.0.0.1:8787 — broker desactivado',flush=True)
    HTTPServer(('127.0.0.1',int(os.getenv('PORT','8787'))),Handler).serve_forever()
