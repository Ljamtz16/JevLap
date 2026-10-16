import json
import sqlite3
import unittest
from datetime import datetime
import session_results as views


class SessionResultsTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:')
        self.db.execute('CREATE TABLE decisions(id TEXT PRIMARY KEY,body TEXT NOT NULL)')
        self.add('old','2026-10-09T01:00:00Z',pnl=100)
        views.index_results(self.db)
        for i in range(600):self.add(str(i),'2026-10-09T14:00:00Z',pnl=1,session_date='2026-10-09')
        self.add('next','2026-10-10T04:00:00Z',pnl=10)

    def tearDown(self):self.db.close()

    def add(self,id,stamp,pnl,**extra):
        body=dict(id=id,timestamp=stamp,symbol='SPY',side='CALL',confidence=.8,status='CLOSED',pnl=pnl,snapshot={'big':'x'*1000},**extra)
        self.db.execute('INSERT OR REPLACE INTO decisions VALUES(?,?)',(id,json.dumps(body)))

    def test_default_day_page_limit_full_selection_summary(self):
        old=views.today
        try:
            views.today=lambda:'2026-10-09'
            result=views.results(self.db,{})
        finally:views.today=old
        self.assertEqual(result['total'],600)
        self.assertEqual(len(result['rows']),250)
        self.assertEqual(result['summary']['pnl'],600)
        self.assertTrue(all('snapshot' not in r for r in result['rows']))
        page=views.results(self.db,dict(day=['2026-10-09'],offset=['250']))
        self.assertFalse({r['id'] for r in result['rows']} & {r['id'] for r in page['rows']})
        self.assertEqual(len(views.results(self.db,dict(day=['all'],limit=['9999']))['rows']),500)

    def test_ny_midnight_and_filters(self):
        self.assertEqual(views.results(self.db,dict(day=['2026-10-08']))['summary']['pnl'],100)
        self.assertEqual(views.results(self.db,dict(day=['2026-10-10']))['total'],1)
        self.assertEqual(views.results(self.db,dict(day=['2026-10-09'],symbol=['QQQ']))['total'],0)
        self.assertEqual(views.results(self.db,dict(day=['all'],confidence=['.9']))['total'],0)
        with self.assertRaises(ValueError):views.results(self.db,dict(day=['bad']))
        with self.assertRaises(ValueError):views.results(self.db,dict(confidence=['2']))

    def test_dst_boundaries(self):
        for day,hours in [('2026-03-08',23),('2026-11-01',25)]:
            a,b=map(datetime.fromisoformat,views.day_bounds(day))
            self.assertEqual((b-a).total_seconds()/3600,hours)

    def test_projection_tracks_insert_replace_update_delete(self):
        self.add('0','2026-10-09T14:00:00Z',pnl=10,session_date='2026-10-09')
        self.assertEqual(views.results(self.db,dict(day=['2026-10-09']))['summary']['pnl'],609)
        self.db.execute("UPDATE decisions SET body=json_set(body,'$.pnl',20) WHERE id='0'")
        self.assertEqual(views.results(self.db,dict(day=['2026-10-09']))['summary']['pnl'],619)
        self.db.execute("DELETE FROM decisions WHERE id='0'")
        self.assertEqual(views.results(self.db,dict(day=['2026-10-09']))['total'],599)
        views.index_results(self.db)
        self.assertEqual(views.results(self.db,dict(day=['all']))['total'],601)

    def test_session_index_and_scoped_local_ledger(self):
        counts={r['day']:r['decisions'] for r in views.sessions(self.db)['sessions']}
        self.assertEqual(counts['2026-10-08'],1)
        self.assertEqual(counts['2026-10-09'],600)
        state=dict(cash=100,live_ledger=[dict(entry_time='2026-10-09T01:00:00Z',status='CLOSED',net_pnl=10),dict(entry_time='2026-10-09T14:00:00Z',status='CLOSED',net_pnl=2)])
        result=views.scope_local_state(state,dict(day=['2026-10-09']))
        self.assertEqual(result['cash'],100)
        self.assertEqual(result['session_realized_net_pnl'],2)
        self.assertEqual(len(state['live_ledger']),2)


if __name__=='__main__':unittest.main()
