"""Confidence diagnostics and day-held-out calibration of an explicit win target.

P(response) is never interpreted as P(profit). A fitted confidence-to-win mapping
is a new empirical model for a frozen execution policy, not provider calibration.
"""
import argparse
import hashlib
import json
import sqlite3
from collections import defaultdict, Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from session_policy import stamp, NY

ROOT = Path(__file__).resolve().parent
MIN_TRAIN_DAYS, MIN_TEST_DAYS, MIN_TRAIN, MIN_TEST = 20, 5, 100, 25


def isotonic_fit(samples):
    grouped = defaultdict(list)
    for x, y in samples:
        grouped[x].append(y)
    blocks = []
    for x, ys in sorted(grouped.items()):
        blocks.append([x, x, sum(ys), len(ys)])
        while len(blocks) > 1 and blocks[-2][2] / blocks[-2][3] > blocks[-1][2] / blocks[-1][3]:
            b = blocks.pop(); a = blocks.pop()
            blocks.append([a[0], b[1], a[2]+b[2], a[3]+b[3]])
    return [dict(low=a, high=b, probability=s/n, n=n) for a,b,s,n in blocks]


def predict(blocks, x):
    return min(blocks, key=lambda b: max(b['low']-x, x-b['high'], 0))['probability']


def wilson(wins, n):
    if not n:
        return None
    z=1.96; p=wins/n; denom=1+z*z/n
    center=(p+z*z/(2*n))/denom
    radius=z*((p*(1-p)/n+z*z/(4*n*n))**.5)/denom
    return [max(0.,center-radius),min(1.,center+radius)]


def analyze(rows, as_of=None):
    as_of = as_of or datetime.now(timezone.utc)
    groups, exclusions = defaultdict(list), Counter()
    for row in sorted(rows, key=lambda r: stamp(r['timestamp'])):
        if stamp(row['timestamp']) > as_of:
            exclusions['FUTURE_DECISION'] += 1; continue
        if row.get('research_mode') != 'snapshot_shadow' or row.get('side') not in ('CALL','PUT'):
            exclusions['NOT_PROSPECTIVE_DIRECTIONAL_SHADOW'] += 1; continue
        if row.get('status') != 'CLOSED' or row.get('pnl') is None or not row.get('exit_timestamp'):
            exclusions['UNRESOLVED_OR_NO_EXECUTED_SHADOW'] += 1; continue
        if stamp(row['exit_timestamp']) > as_of:
            exclusions['FUTURE_EXIT'] += 1; continue
        # Segment incompatible policies, models, symbols and original datasets.
        identity = dict(model=row.get('model'),symbol=row['symbol'],config=row['config'],
                        simulation_version=row.get('simulation_version'),dataset_policy=row.get('dataset_policy'))
        key = hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()[:16]
        groups[key].append(dict(identity=identity,row=row))
    summaries = []
    for key, members in groups.items():
        rows = [m['row'] for m in members]
        bands = []
        for lo,hi in [(0,.75),(.75,.80),(.80,.85),(.85,.90),(.90,1.001)]:
            selected = [r for r in rows if lo <= r['confidence'] < hi]
            wins = sum(r['pnl'] > 0 for r in selected)
            bands.append(dict(low=lo,high=min(hi,1.),n=len(selected),wins=wins,
                              observed_win_rate=wins/len(selected) if selected else None,
                              wilson_95=wilson(wins,len(selected))))
        # One opportunity per symbol with a 60-minute embargo AND no overlapping exits.
        independent, last_end = [], None
        for row in rows:
            ts = stamp(row['timestamp'])
            if last_end is not None and ts < last_end:
                continue
            independent.append(row)
            last_end = max(ts+timedelta(minutes=60),stamp(row['exit_timestamp']))
        days = sorted({stamp(r['timestamp']).astimezone(NY).date().isoformat() for r in independent})
        status, blocks, metrics = 'INSUFFICIENT_INDEPENDENT_DAYS', None, None
        split = max(MIN_TRAIN_DAYS, len(days)-MIN_TEST_DAYS)
        train_days, test_days = days[:split], days[split:]
        train = [r for r in independent if stamp(r['timestamp']).astimezone(NY).date().isoformat() in train_days]
        test = [r for r in independent if stamp(r['timestamp']).astimezone(NY).date().isoformat() in test_days]
        if len(train_days) >= MIN_TRAIN_DAYS and len(test_days) >= MIN_TEST_DAYS:
            if len(train) < MIN_TRAIN or len(test) < MIN_TEST or len({r['pnl'] > 0 for r in train}) < 2:
                status = 'INSUFFICIENT_NONOVERLAPPING_LABELS'
            else:
                blocks = isotonic_fit([(r['confidence'],int(r['pnl'] > 0)) for r in train])
                base = sum(r['pnl'] > 0 for r in train)/len(train)
                brier = sum((predict(blocks,r['confidence'])-int(r['pnl'] > 0))**2 for r in test)/len(test)
                reference = sum((base-int(r['pnl'] > 0))**2 for r in test)/len(test)
                metrics = dict(heldout_brier=brier,train_base_rate_brier=reference,
                               improves_train_base_rate=brier < reference,
                               heldout_n=len(test),heldout_wins=sum(r['pnl'] > 0 for r in test))
                status = 'CANDIDATE_REQUIRES_REVIEW'
        summaries.append(dict(key=key,identity=members[0]['identity'],status=status,
                              target='SHADOW_GROSS_PNL_POSITIVE_UNDER_FROZEN_POLICY',
                              raw_decisions=len(rows),confidence_bands_descriptive_only=bands,
                              independent_labels=len(independent),independent_days=len(days),
                              train_days=train_days,test_days=test_days,train_n=len(train),test_n=len(test),
                              mapping=blocks,metrics=metrics))
    available=[r for r in rows if stamp(r['timestamp'])<=as_of and r.get('research_mode')=='snapshot_shadow']
    qualified=[r for r in available if r.get('side') in ('CALL','PUT') and r.get('confidence',0)>=.75]
    diagnostics=dict(session_days=len({stamp(r['timestamp']).astimezone(NY).date() for r in available}),decisions=len(available),direction_counts=dict(Counter(r.get('side') for r in available)),
                     qualified_directional_decisions=len(qualified),
                     maximum_directional_confidence=max([r.get('confidence',0) for r in available if r.get('side') in ('CALL','PUT')]+[0]),
                     closed_profit_labels=sum(s['raw_decisions'] for s in summaries))
    return dict(version='jev_confidence_diagnostics_v1',generated_at_utc=as_of.isoformat(),diagnostics=diagnostics,
                status='INSUFFICIENT_INDEPENDENT_DAYS' if not summaries or all(s['status'].startswith('INSUFFICIENT') for s in summaries) else 'REVIEW_REQUIRED',
                trading_threshold=.75,auto_apply=False,provider_probabilities_unchanged=True,
                probability_semantics='P_RESPONSE_IS_NOT_P_PROFIT',
                target='SHADOW_GROSS_PNL_POSITIVE_UNDER_FROZEN_POLICY',
                requirements=dict(train_days=MIN_TRAIN_DAYS,test_days=MIN_TEST_DAYS,train_labels=MIN_TRAIN,test_labels=MIN_TEST),
                exclusions=dict(exclusions),segments=summaries)


def run(root=ROOT):
    with sqlite3.connect('file:'+str(root/'data/lab.sqlite')+'?mode=ro',uri=True) as db:
        rows=[json.loads(r[0]) for r in db.execute('SELECT body FROM decisions')]
    report=analyze(rows)
    out=root/'data/calibration-analysis.json';tmp=out.with_suffix('.tmp')
    tmp.write_text(json.dumps(report,indent=2,allow_nan=False));tmp.replace(out)
    print(json.dumps(dict(status=report['status'],segments=len(report['segments']),threshold=.75,
                         maximum_days=max([s['independent_days'] for s in report['segments']]+[0]))))
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,default=ROOT)
    run(parser.parse_args().root)
