# Jev Lab v0.1

Independent local research application. Does not read or modify options-system.

## Start

Python 3.10 or newer; no external dependencies.

```bash
cd jev-lab
python3 server.py
```

Open http://127.0.0.1:8787. Demo mode uses clearly labeled synthetic decisions and results, without external requests. The HTML can also be opened directly for demo exploration.

To query Jev, obtain a key from https://console.typesafe.ai, set TYPESAFE_API_KEY privately in the server environment and restart the server. The app does not load .env automatically. Import a JSON matching example_snapshot.json, then press Consultar Jev. This makes a potentially billable API request. The example contains historical invented data; it is only a schema example, not a trade recommendation or a prospective observation. Model version can be configured with JEV_MODEL; returned version, original request, response and token usage are persisted. Keys never enter the UI or database.

## What works

- Independent responsive interface, filters, JSON export and decision detail.
- Demo P&L curve, grouped comparison and confidence bands.
- Real TypeSafe HTTP client, output validation and strict market-state allowlist.
- SQLite decision persistence and deduplication by timestamp + underlying.
- Research evaluator using entry ask / exit bid, 15/30/60 minute horizons, TP/SL/time exits, MFE and MAE while holding.
- Six tests for entry/exit conventions, low confidence, causal quote timestamps, missing horizons and first stop.

## Important boundaries

No Alpaca executor or account credentials are included. Broker orders are disabled. No automatic snapshot watcher is included because the existing file schema is unavailable. No unattended deployment is performed. Future evaluation is available through the CLI below; live UI reload reads updated stored records. One-contract outcomes are independent research episodes, not a capital-constrained portfolio. The max-position, daily-loss, market-hours and EOD controls must be implemented in the broker service before enabling orders. Do not expose this unauthenticated local server publicly. Bind to localhost and use an SSH tunnel on the VPS.

Confidence and probability of the selected choice are distinct fields. Neither measures validated probability of profit. No known financial predictive skill is established. Missing horizons stay null; fills are not invented. Horizon returns can extend past the deterministic exit as counterfactual research observations. MFE/MAE only cover the observed holding period; sparse snapshots cannot prove the intrabar order of TP and SL. Fees and slippage beyond quoted bid/ask are not modeled.

## Evaluate stored decisions

Create a JSON array of quotes: [{"symbol":"...","timestamp":"ISO with timezone","bid":1.50}].

```bash
python3 track.py quotes.json
python3 -m unittest discover -s tests -v
```

Each decision freezes its snapshot, contract selection and configuration. Quotes must be complete historical observations available for evaluation, never sent to Jev. Updates recalculate from all supplied quotes, so provide the accumulated chronological observations, not only the latest batch.

## VPS handoff

Copy this folder into ~/jev-lab, create a private environment if preferred and run server.py. Keep data/lab.sqlite backed up. Access over an SSH tunnel: ssh -L 8787:127.0.0.1:8787 user@vps. Next integration needs one actual snapshot, paths to completed files and baseline signals, and separately configured Alpaca paper keys. We must test broker reconciliation, idempotency and exits before activation.

## Access and published cost (checked 2026-10-06)

Official console: https://console.typesafe.ai
Official quick start: https://docs.typesafe.ai/introduction/quickstart
Official endpoint: POST https://api.typesafe.ai/v1/systemone
Homepage input price: US$42 per billion input tokens, equivalent to US$0.042 per million. At 1,000 input tokens each, 10,000 evaluations imply US$0.42 in input charges alone. This is arithmetic from the advertised rate, not a full billing quote; output tokens are free according to the official Models page; minimum spend, credit availability and access limits must be confirmed in the account. There is no verified free-tier promise in this deliverable.

## Git / VPS snapshot consumer

Published as the independent repository https://github.com/Ljamtz16/JevLap. Production Options-System remains separate.

Use a separate checkout, not the production options-system folder:

```bash
git clone https://github.com/Ljamtz16/JevLap.git ~/jev-lab
cd ~/jev-lab
python3 -m unittest discover -s tests -v
python3 watch_snapshots.py --source ~/options-system/data/raw/intraday --once
```

Set credentials in a private environment file outside the repository, e.g. ~/.config/jev-lab/credentials.env with permissions 600. Windows DPAPI credentials cannot be copied to Linux. Use TYPESAFE_API_KEY, ALPACA_PAPER_API_KEY and ALPACA_PAPER_SECRET_KEY. The two sample systemd units load that file. Install units only after checking paths and confirming the actual VPS snapshot schema.

The worker verifies the immutable-envelope checksum, consumes completed JSON only, deduplicates decisions, accumulates option quotes and updates research outcomes. Old files contribute quotes but never trigger retrospective Jev requests. Fresh files (maximum age 120 seconds) can incur Jev API charges. Broker remains disabled. Shadow research entry is the observed snapshot ask, not a broker fill; inference latency means this is not an executable fill assumption. Baseline comparisons remain unset until a verified signal-file adapter exists. The adapter targets the checked-in collector schema, not yet a verified VPS sample. Missing option volume or stale quotes reject an entry.
