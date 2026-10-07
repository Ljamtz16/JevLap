from contextlib import closing
"""Dashboard transfers summaries while preserving full decision audit records."""
import json, sqlite3, tempfile, threading, unittest
from pathlib import Path
from urllib.request import urlopen
from urllib.error import HTTPError
from unittest.mock import patch
import server

class DashboardAPITests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.path=Path(self.tmp.name)/'lab.sqlite'
        self.row=dict(id='test-id',symbol='SPY',status='SKIP',confidence=.44,
                      raw={'large':'x'*50000},snapshot={'contracts':['x'*50000]},
                      request={'state':'x'*50000},config={'threshold':.75})
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('CREATE TABLE decisions(id TEXT PRIMARY KEY,body TEXT NOT NULL)')
            db.execute('INSERT INTO decisions VALUES(?,?)',('test-id',json.dumps(self.row)))
        self.patch=patch.object(server,'DB',self.path);self.patch.start()
        self.http=server.HTTPServer(('127.0.0.1',0),server.Handler)
        self.thread=threading.Thread(target=self.http.serve_forever,daemon=True);self.thread.start()
    def tearDown(self):
        self.http.shutdown();self.http.server_close();self.thread.join()
        self.patch.stop();self.tmp.cleanup()
    def get(self,path):
        return urlopen('http://127.0.0.1:'+str(self.http.server_port)+path,timeout=5)
    def test_summary_small_and_audit_record_preserved(self):
        with self.get('/api/results') as response:
            body=response.read();self.assertLess(len(body),2000)
            self.assertEqual(response.headers['Cache-Control'],'no-store')
        result=json.loads(body);row=result['rows'][0]
        self.assertEqual(row['confidence'],.44);self.assertEqual(row['config'],{'threshold':.75})
        self.assertTrue(all(field not in row for field in ('raw','snapshot','request')))
        with self.get('/api/decision?id=test-id') as response:
            self.assertEqual(json.load(response),self.row)
        with closing(sqlite3.connect(self.path)) as db, db:
            self.assertEqual(json.loads(db.execute('SELECT body FROM decisions').fetchone()[0]),self.row)
    def test_unknown_detail_returns_404(self):
        with self.assertRaises(HTTPError) as caught:self.get('/api/decision?id=missing')
        self.assertEqual(caught.exception.code,404)
    def test_local_account_and_analysis_are_separate_readonly_endpoints(self):
        root=Path(self.tmp.name);art=root/'artifacts/intraday';art.mkdir(parents=True)
        state={'cash':703.8,'mode':'LIVE_PAPER','live_ledger':[]}
        (art/'PAPER_TRADING_LIVE_STATE_V01.json').write_text(json.dumps(state))
        with patch.object(server,'SYSTEM_ROOT',root):
            with self.get('/api/local-paper') as response:
                value=json.load(response)
            self.assertEqual(value['state'],state);self.assertEqual(value['account_kind'],'LOCAL_SIMULATION')
            with self.get('/api/analysis') as response:
                self.assertFalse(json.load(response)['entry_controls']['auto_apply'])
