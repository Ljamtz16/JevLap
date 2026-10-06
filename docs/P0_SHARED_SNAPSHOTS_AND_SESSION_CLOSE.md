# P0 · Shared SPY captures and intraday session boundaries

Effective canonical source date: **2026-10-07 (New York)**. SPY decisions in Jev and the Comparator use the exact immutable `data/raw/prospective/spy_options_*.json` envelope used by Options-System. No additional chain request is made. The original payload SHA-256, capture time and capture ID are retained. SPY from the separate intraday collection is excluded from both consumers after this date; other symbols retain their existing intraday source. A missing canonical capture never falls back silently to the other chain. Historical provider decisions remain frozen and are not requested again.

Options' prospective dataset exports `snapshot_sha256` and uses the same causal quote/daily-bar filtering as the Comparator. Future-dated source records do not enter chain features. The Comparator requires identical source-file and payload hash for canonical joins. Sorting both sources by capture filename preserves previous-snapshot feature order.

Simulation version: **intraday_session_v2**. Entry and exit quotes stay inside the entry's New York regular session. The capture's `market_clock.next_close` supplies early closes when available; otherwise the regular 16:00 ET boundary is used. Replay accepts an explicit `as_of` time. A bid from another day, after close, or after `as_of` cannot close a position or populate horizons/MFE/MAE.

* `CLOSED` / `SESSION_CLOSE`: an observed bid from the last 120 seconds of the session supplies the simulated exit. The exact quote timestamp and bid are stored. This is not a broker fill.
* `EXPIRED`: a same-day-expiry contract lacks a valid closing bid. P&L remains null; settlement is not guessed.
* `INCOMPLETE`: a nonexpired contract lacks a valid closing bid. P&L remains null, not zero.
* `OPEN`: the session has not ended and no ordinary TP/SL/time exit occurred.

The Jev worker refreshes research observations even if no new file arrives after the bell. Auxiliary H02 records now retain the complete research entry/exit record. Aggregates include P&L only for CLOSED simulations.

For local Options accounts, unresolved positions retain their debited capital, cannot take marks from a later session, and carry `pending_reconciliation=true`. Account equity is explicitly flagged as an estimate when any position is unresolved. No cash is released or zero-P&L close fabricated.

Before rollout, back up the SQLite database with the SQLite backup API and preserve current code/state. Rescoring comparison observations under v2 must be identified as a correction, with the original database and exported session report retained. The canonical-source switch is prospective; today's two distinct SPY chains are not rewritten into identical captures.

Unchanged research rules: Jev confidence threshold 75%, frozen hypothesis predicates, existing quantity/risk policies. Executable-contract selection and cooldown/simultaneity/drawdown analysis are later priorities.
