from contextlib import closing,redirect_stdout
from io import StringIO
import json,sqlite3,tempfile,unittest,zipfile
from pathlib import Path
from analyze_session import in_session,first_activations,stats,run,jev_report

class SessionAnalysisTests(unittest.TestCase):
    def test_new_york_session_not_utc_day(self):
        self.assertTrue(in_session('2026-10-07T01:00:00Z','2026-10-06'))
        self.assertFalse(in_session('2026-10-06T01:00:00Z','2026-10-06'))
    def test_unknown_and_repeated_events_not_zero_profit(self):
        self.assertIsNone(stats([{'status':'OPEN','pnl':None}])['simulated_pnl_gross'])
        hits=[dict(timestamp='2026-10-06T14:'+m+':00Z',symbol='SPY',hypothesis='H02') for m in ('00','01','02','10')]
        self.assertEqual(len(first_activations(hits)),2)
    def test_scope_and_reconstruction_separate(self):
        base=dict(id='one',symbol='SPY',timestamp='2026-10-06T14:00:00Z',side='CALL',confidence=.8,status='CLOSED',contract='C',pnl=10,reason='TIME')
        comp=dict(signal=dict(evaluation_mode='RECONSTRUCTED',status='READY',hypotheses=[{'id':'H03'}]),group='Coinciden',system_simulation=base,auxiliary_15m=[])
        row=dict(base,baseline='CALL',comparison=comp)
        report=jev_report([row,dict(base,id='two',comparison=None)])
        self.assertEqual(report['comparison']['PROSPECTIVE']['records'],0)
        self.assertEqual(report['comparison']['RECONSTRUCTED']['hypotheses']['H03']['snapshot_simulations']['closed'],1)
        self.assertEqual(report['without_comparison'],1)
    def test_export_read_only_no_secrets_and_target_date(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);lab=root/'lab';(lab/'data').mkdir(parents=True)
            system=root/'options';(system/'artifacts/intraday').mkdir(parents=True)
            (system/'artifacts/intraday/HYPOTHESIS_DAILY_REPORT_V02.json').write_text(json.dumps({'days':{}}))
            path=lab/'data/lab.sqlite'
            row=dict(id='r',timestamp='2026-10-06T14:00:00Z',symbol='SPY',side='NO_TRADE',confidence=.3,status='SKIP',reason='low',comparison=None,snapshot={'private':'input'},request={'Authorization':'secret'},raw={'test':'provider'})
            with closing(sqlite3.connect(path)) as db,db:
                db.execute('CREATE TABLE decisions(id TEXT PRIMARY KEY,body TEXT)')
                db.execute('INSERT INTO decisions VALUES(?,?)',('r',json.dumps(row)))
            before=path.read_bytes()
            with redirect_stdout(StringIO()):report=run(lab,system,'2026-10-06',root/'export')
            self.assertEqual(path.read_bytes(),before)
            self.assertEqual(report['jev']['decisions'],1)
            self.assertIsNone(report['options_system']['session_daily_report'])
            with zipfile.ZipFile(root/'export.zip') as zipped:
                text=zipped.read('jev_decisions.json').decode()
                self.assertNotIn('Authorization',text);self.assertNotIn('snapshot',json.loads(text)[0])
                self.assertNotIn('paper.sqlite',zipped.namelist())

if __name__=='__main__':unittest.main()
