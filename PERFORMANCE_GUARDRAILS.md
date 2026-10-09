# Jev runtime performance guardrails

Validated 2026-10-09/10 on `bmv-neuro-lab` after the 65% observation-freeze change.

## Problem found

The worker refreshed every historical decision every 10 seconds and the comparator rebuilt every comparison every 20 seconds. With 8,509 decisions, 9,243 comparison signals and about 2.5 million option quotes, the comparator was averaging about 46% CPU and 478 MB RSS; the worker was about 15% CPU.

## Runtime design now

- `watch_snapshots.py` loads the consumed-path set once per cycle, reuses one SQLite connection and refreshes only decisions whose status is `OPEN`.
- `compare_system.py` persists `comparison_consumed`, `comparison_pending` and `comparison_runtime` in SQLite.
- New decisions are discovered by SQLite `rowid`; finalized comparisons are removed from the pending queue.
- Restarts reuse persisted consumed paths and `last_decision_rowid` instead of rebuilding history.
- The first migration may scan existing rows once to preserve unfinished work. Normal restarts do not.

## Measured result

Normal no-new-data run: worker 0.10 s / 26 MB RSS; comparator 0.11 s / 28 MB RSS. Stable services measured about 0.2–0.3% CPU each and 27–29 MB RSS. The VPS had roughly 6.6 GiB RAM available and zero CPU/memory pressure after the change.

## cgroup protection on VPS

The user units `jev-lab-worker-user.service` and `jev-lab-comparison-user.service` are configured with:

```ini
Nice=10
CPUQuota=50%
MemoryMax=384M
OOMScoreAdjust=500
```

Paper execution and the Jev HTTP server are intentionally not assigned these research-process limits.
