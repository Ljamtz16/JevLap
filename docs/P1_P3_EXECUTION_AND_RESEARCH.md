# P1–P3 · Executable contracts and controlled research

Effective date: 2026-10-07, New York. Original provider decisions, probabilities and historical execution configurations remain frozen. No historical fill or live account balance is rewritten.

## P1

`options_system.executable_contracts` is the only new selector; Jev loads this exact module from the sibling Options-System repository (or `OPTIONS_SYSTEM_ROOT`). Both repositories must be updated together. It searches the captured chain for a whole-contract premium within the cash allocation, 1–10 calendar days to expiry, fresh same-session quotes, positive volume, bid/ask sizes sufficient for quantity, and acceptable spread. Absolute delta must be 0.25–0.75, ranked toward 0.50. If delta is absent, the strike must be within 1% of spot. A cheaper distant strike does not bypass these checks. Missing required liquidity fails closed. The selected contract, DTE, delta/ATM basis, premium budget and rejection counts are recorded.

Jev/Comparator use a reference cash of $1,000 and a 20% premium allocation per independent opportunity, quantity 1 and their frozen TP/SL policies. This is not an account or a maximum-loss-at-stop guarantee. LIVE_PAPER uses the separately selected allocation from its existing control file and now enforces one contract per trade. Alpaca Paper rechecks current quotes, tradability and buying power, including limit-price rounding; the premium allocation is configurable via `JEV_PAPER_PREMIUM_FRACTION` (default 20%). Exits remain independent of entry limits.

H02 retains entry/quote timestamps, contract, quantity, capital, bid/ask, exit bid/time, reason and P&L in Jev exports and local account ledgers. Jev and Comparator are independent snapshot simulations. LIVE_PAPER is a local virtual account. ALPACA_PAPER is a broker account measured from confirmed fills. Their balances and P&L remain separate in both dashboards; unresolved P&L is null.

## P2

`analyze_entry_controls.py` produces 13 causal counterfactuals, with identical signals, captured chains, cash allocation, fees and one-contract cap: baseline; H01 cooldown after confirmed exit of 5/10/15/30 minutes; one position per hypothesis; consecutive-loss halts of 2/3/4; daily drawdown halts of 2/5/10%; and a combined candidate. Pending unresolved positions count toward the position cap. Closed outcomes affect limits only after their exit time. Loss and drawdown halts latch for the New York session. Daily drawdown uses observed bid-marked equity from the session peak. Exits always execute before entry controls.

These scenarios are diagnostics. New limits are not activated automatically. Existing LIVE_PAPER controls default to disabled; explicit controls can be placed in its separate `entry_controls` control object after review. At least 20 independent signal days are required for review, not proof of effectiveness. The report includes blocked reasons, cash/equity, unresolved positions, per-day drawdown, loss streaks and a hashed input manifest.

## P3

The Jev threshold remains 75%. P(response) is not P(profit), and the provider probabilities are never overwritten. `calibration_analysis.py` first reports the number of eligible decisions and resolved shadow outcomes. It can fit a separate monotone confidence-to-win mapping for the explicit target **positive gross shadow P&L under the frozen execution policy**. It does not represent net profitability, broker fills or calibration of the provider's categorical choice probabilities.

Models, symbols, datasets and execution configurations are segmented. Opportunities are separated by at least 60 minutes and do not overlap exit times. Training requires 20 earlier days and 100 labeled opportunities with both outcomes; holdout requires 5 subsequent days and 25 labels. An isotonic mapping is assessed with holdout Brier score against the training base rate. Candidates always require review; no threshold, mapping or policy is applied automatically. One observed day, missing outcomes or zero eligible trades produce an explicit insufficient-data status.

The live publisher and post-close pipeline refresh P2/P3 reports before dashboard metadata. This performs no Jev requests and submits no broker orders. Outputs are `ENTRY_CONTROLS_ANALYSIS_V01.json` in Options-System and `data/calibration-analysis.json` in Jev. Original immutable captures remain unchanged.
