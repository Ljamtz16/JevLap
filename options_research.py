import json
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

VERSION = "JEV_OPTIONS_RESEARCH_BRIDGE_V01"
SYMBOLS = ["SPY","QQQ","IWM","AAPL","NVDA","MSFT","AMZN","META","TSLA"]
MATCH_WINDOW_SECONDS = 90


def _load(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {} if default is None else default


def _dt(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _today_ny():
    return datetime.now(ZoneInfo("America/New_York")).date().isoformat()


def _day(row):
    return row.get("decision_date") or row.get("market_date") or row.get("session_date") or str(row.get("signal_time") or row.get("timestamp") or "")[:10]


def _side(value):
    value = str(value or "").upper()
    return value if value in {"CALL","PUT","NO_TRADE"} else value


def _root_from_contract(contract):
    text = str(contract or "")
    for symbol in SYMBOLS:
        if text.startswith(symbol):
            return symbol
    return None


def _metric(horizons, horizon):
    return (horizons or {}).get(str(horizon), {})


def _as_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _max_drawdown_pnl(pnls):
    if not pnls:
        return None
    equity = peak = worst = 0.0
    for pnl in pnls:
        equity += pnl
        peak = max(peak, equity)
        worst = min(worst, equity - peak)
    return worst


def _paper_risk_metrics(rows):
    pnls, mfe_pnl, mae_pnl = [], [], []
    for row in rows:
        pnl = _as_float(row.get("pnl"))
        if pnl is not None:
            pnls.append(pnl)
        entry = _as_float(row.get("entry_ask"))
        qty = _as_float(row.get("quantity")) or 1.0
        mfe = _as_float(row.get("mfe"))
        mae = _as_float(row.get("mae"))
        if entry is not None and entry > 0 and mfe is not None:
            mfe_pnl.append(entry * 100.0 * qty * mfe)
        if entry is not None and entry > 0 and mae is not None:
            mae_pnl.append(entry * 100.0 * qty * mae)
    return {
        "mean_mfe_pnl": sum(mfe_pnl) / len(mfe_pnl) if mfe_pnl else None,
        "mean_mae_pnl": sum(mae_pnl) / len(mae_pnl) if mae_pnl else None,
        "max_drawdown_pnl": _max_drawdown_pnl(pnls),
    }


def _strategy_row(strategy, source, side, evidence, episodes=0, metrics=None,
                  entries=None, closed=None, opened=None, pnl=None, wins=None, pnl_basis=None):
    metrics = metrics or {}
    n = metrics.get("n")
    win_rate = metrics.get("win_rate")
    if wins is not None and closed:
        win_rate = wins / closed
    if pnl is None and metrics.get("total_pnl_1_contract") is not None:
        pnl = metrics.get("total_pnl_1_contract")
    mean_pnl = metrics.get("mean_pnl_1_contract")
    if mean_pnl is None and pnl is not None and closed:
        mean_pnl = float(pnl) / closed
    return {
        "strategy": strategy, "source": source, "side": _side(side), "evidence": evidence,
        "episodes": episodes, "entries": episodes if entries is None else entries,
        "closed": 0 if closed is None else closed, "open": 0 if opened is None else opened,
        "n": n, "win_rate": win_rate, "mean_return": metrics.get("mean_return"),
        "mean_mfe": metrics.get("mean_mfe"), "mean_mae": metrics.get("mean_mae"),
        "tp10_before_sl10_rate": metrics.get("tp10_before_sl10_rate"),
        "pnl": pnl, "mean_pnl": mean_pnl, "pnl_n": metrics.get("pnl_1_contract_n") or closed,
        "mean_mfe_pnl": metrics.get("mean_mfe_pnl") if metrics.get("mean_mfe_pnl") is not None else metrics.get("mean_mfe_pnl_1_contract"),
        "mean_mae_pnl": metrics.get("mean_mae_pnl") if metrics.get("mean_mae_pnl") is not None else metrics.get("mean_mae_pnl_1_contract"),
        "max_drawdown_pnl": metrics.get("max_drawdown_pnl") if metrics.get("max_drawdown_pnl") is not None else metrics.get("max_drawdown_pnl_1_contract"),
        "pnl_basis": pnl_basis,
    }


def _read_jsonl(path):
    out = []
    try:
        with Path(path).open(encoding="utf-8") as handle:
            for line in handle:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        pass
    return out


def _jev_decisions(db_path, day):
    if not Path(db_path).exists():
        return []
    with sqlite3.connect(str(db_path), timeout=20) as db:
        table = "decisions_dashboard" if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='decisions_dashboard'").fetchone() else "decisions"
        rows = db.execute(
            f"SELECT body FROM {table} WHERE json_extract(body,'$.session_date')=? ORDER BY rowid",
            (day,),
        ).fetchall()
    out = []
    for (body,) in rows:
        try:
            row = json.loads(body)
        except ValueError:
            continue
        if day and _day(row) != day:
            continue
        out.append({
            "id": row.get("id"), "time": row.get("timestamp"), "day": _day(row),
            "symbol": row.get("symbol"), "side": _side(row.get("side")),
            "confidence": row.get("confidence"), "status": row.get("status"),
            "active": row.get("status") not in {None, "SKIP"} and bool(row.get("contract")),
            "pnl": row.get("pnl"), "contract": row.get("contract"),
        })
    return out


def _put_closes(events):
    out = {}
    for event in events:
        if event.get("event") == "PAPER_POSITION_CLOSED":
            out[event.get("signal_id")] = {
                "status": "CLOSED", "pnl": event.get("net_pnl"),
                "result": event.get("reason"), "exit_time": event.get("logged_at_utc"),
            }
    return out


def _normalize_live(options_root, day):
    a = Path(options_root) / "artifacts/intraday"
    rows = []
    local = _load(a / "PAPER_TRADING_LIVE_STATE_V01.json", {})
    for item in list(local.get("live_ledger") or []) + list(local.get("open_positions") or []):
        if day and _day(item) != day:
            continue
        rows.append({
            "id": item.get("signal_id"), "time": item.get("signal_time") or item.get("entry_time"),
            "day": _day(item), "symbol": _root_from_contract(item.get("contract")) or "SPY",
            "side": _side(item.get("side")), "source": "Frozen", "strategy": item.get("hypothesis"),
            "contract": item.get("contract"), "status": item.get("status"),
            "pnl": item.get("net_pnl"), "result": item.get("exit_reason"),
            "entry_ask": item.get("entry_ask"), "quantity": item.get("quantity") or 1,
            "mfe": item.get("mfe"), "mae": item.get("mae"),
            "evidence": "PAPER", "broker_order": False,
        })
    put = _load(a / "PUT_CONFIRM_LIVE_STATE_V02.json", {})
    put_closes = _put_closes(_read_jsonl(a / "PUT_CONFIRM_LIVE_EVENTS_V02.jsonl"))
    for item in put.get("signals") or []:
        if day and _day(item) != day:
            continue
        close = put_closes.get(item.get("signal_id"), {})
        rows.append({
            "id": item.get("signal_id"), "time": item.get("signal_time"), "day": _day(item),
            "symbol": _root_from_contract(item.get("contract")) or "SPY", "side": "PUT",
            "source": "PUT v0.2", "strategy": "PUT_CONFIRM_V02", "contract": item.get("contract"),
            "status": close.get("status", item.get("paper_status")), "pnl": close.get("pnl"),
            "entry_ask": item.get("entry_ask"), "quantity": item.get("quantity") or 1,
            "mfe": item.get("mfe"), "mae": item.get("mae"),
            "result": close.get("result"), "evidence": "PROSPECTIVE", "broker_order": True,
        })
    for filename, source in [
        ("H09_PUT_FLOW_LIVE_STATE_V01.json", "H09"),
        ("MULTISYMBOL_LIVE_STATE_V01.json", "Multi-Symbol"),
    ]:
        state = _load(a / filename, {})
        for item in state.get("signals") or []:
            if day and _day(item) != day:
                continue
            rows.append({
                "id": item.get("signal_id"), "time": item.get("signal_time"), "day": _day(item),
                "symbol": item.get("symbol") or "SPY", "side": _side(item.get("side")),
                "source": source, "strategy": item.get("candidate_id"), "contract": item.get("contract"),
                "status": "SHADOW", "pnl": None, "result": None,
                "evidence": "PROSPECTIVE", "broker_order": False,
            })
    return sorted(rows, key=lambda x: x.get("time") or "")


def _strategy_results(options_root, day, live_rows):
    a = Path(options_root) / "artifacts/intraday"
    result = []
    grouped = defaultdict(list)
    for row in live_rows:
        if row["source"] in {"Frozen", "PUT v0.2"}:
            grouped[(row["strategy"], row["source"], row["side"])].append(row)
    for (strategy, source, side), rows in grouped.items():
        closed = [r for r in rows if r.get("status") == "CLOSED"]
        risk_metrics = _paper_risk_metrics(closed)
        result.append(_strategy_row(
            strategy, source, side, "PAPER" if source == "Frozen" else "PROSPECTIVE",
            episodes=len(rows), metrics=risk_metrics, entries=len(rows), closed=len(closed),
            opened=len(rows) - len(closed), pnl=sum(float(r.get("pnl") or 0) for r in closed),
            wins=sum(1 for r in closed if float(r.get("pnl") or 0) > 0),
            pnl_basis="PAPER local",
        ))
    h09 = _load(a / "H09_PUT_FLOW_PROSPECTIVE_V01.json", {})
    for cid, payload in (h09.get("discovery", {}).get("by_candidate") or {}).items():
        result.append(_strategy_row(cid, "H09", "PUT", "DISCOVERY", payload.get("episodes", 0), _metric(payload.get("horizons"), 60), pnl_basis="SIM 1c · 60m"))
    h09p = h09.get("prospective", {}).get("by_candidate") or {}
    for cid, payload in h09p.items():
        result.append(_strategy_row(cid, "H09", "PUT", "PROSPECTIVE", payload.get("episodes", 0), _metric(payload.get("horizons"), 60), pnl_basis="SIM 1c · 60m"))
    multi = _load(a / "MULTISYMBOL_DISCOVERY_V01.json", {})
    candidates = {c.get("id"): c for c in multi.get("candidates") or []}
    for cid, payload in (multi.get("discovery", {}).get("by_candidate") or {}).items():
        result.append(_strategy_row(cid, "Multi-Symbol", candidates.get(cid, {}).get("side"), "DISCOVERY", payload.get("episodes", 0), _metric(payload.get("horizons"), 30), pnl_basis="SIM 1c · 30m"))
    multip = _load(a / "MULTISYMBOL_PROSPECTIVE_V01.json", {})
    for cid, payload in (multip.get("summary", {}).get("by_candidate") or {}).items():
        result.append(_strategy_row(cid, "Multi-Symbol", candidates.get(cid, {}).get("side"), "PROSPECTIVE", payload.get("episodes", 0), _metric(payload.get("horizons"), 30), pnl_basis="SIM 1c · 30m"))
    return result


def _by_symbol(options_root, live_rows):
    a = Path(options_root) / "artifacts/intraday"
    multi = _load(a / "MULTISYMBOL_DISCOVERY_V01.json", {})
    by_candidate_symbol = multi.get("discovery", {}).get("by_candidate_symbol") or {}
    candidates = {c.get("id"): c for c in multi.get("candidates") or []}
    out = []
    for symbol in SYMBOLS:
        call = put = 0
        metrics = []
        for cid, symbols in by_candidate_symbol.items():
            payload = (symbols or {}).get(symbol)
            if not payload:
                continue
            side = _side(candidates.get(cid, {}).get("side"))
            if side == "CALL": call += payload.get("episodes", 0)
            if side == "PUT": put += payload.get("episodes", 0)
            m = _metric(payload.get("horizons"), 30)
            if m.get("n"):
                metrics.append((m.get("n", 0), m.get("win_rate"), m.get("mean_return")))
        total_n = sum(m[0] for m in metrics)
        weighted_win = sum(m[0] * (m[1] or 0) for m in metrics) / total_n if total_n else None
        weighted_return = sum(m[0] * (m[2] or 0) for m in metrics) / total_n if total_n else None
        live = [r for r in live_rows if r.get("symbol") == symbol]
        out.append({
            "symbol": symbol, "call_episodes_discovery": call, "put_episodes_discovery": put,
            "live_signals": len(live), "live_call": sum(r["side"] == "CALL" for r in live),
            "live_put": sum(r["side"] == "PUT" for r in live), "win_rate_discovery": weighted_win,
            "mean_return_discovery": weighted_return,
        })
    return out


def _match(jev_rows, option_rows):
    comparisons = []
    used_jev = set()
    for opt in option_rows:
        ot = _dt(opt.get("time"))
        candidates = []
        if ot:
            for j in jev_rows:
                if j.get("symbol") != opt.get("symbol"):
                    continue
                jt = _dt(j.get("time"))
                if jt:
                    delta = abs((jt - ot).total_seconds())
                    if delta <= MATCH_WINDOW_SECONDS:
                        candidates.append((delta, j))
        if candidates:
            delta, j = min(candidates, key=lambda x: x[0])
            used_jev.add(j.get("id"))
            active = bool(j.get("active"))
            same = active and j.get("side") == opt.get("side") and j.get("side") in {"CALL","PUT"}
            opposite = active and {j.get("side"), opt.get("side")} == {"CALL","PUT"}
            group = "Coinciden" if same else "Direcciones opuestas" if opposite else "Options solo"
            comparisons.append({
                "time": opt.get("time"), "symbol": opt.get("symbol"), "options_side": opt.get("side"),
                "options_strategy": opt.get("strategy"), "options_source": opt.get("source"),
                "options_evidence": opt.get("evidence"),
                "jev_side": j.get("side"), "jev_active": active, "jev_status": j.get("status"),
                "jev_confidence": j.get("confidence"), "jev_pnl": j.get("pnl"),
                "group": group, "delta_seconds": delta, "result": opt.get("result"), "options_pnl": opt.get("pnl"),
            })
        else:
            comparisons.append({
                "time": opt.get("time"), "symbol": opt.get("symbol"), "options_side": opt.get("side"),
                "options_strategy": opt.get("strategy"), "options_source": opt.get("source"),
                "options_evidence": opt.get("evidence"),
                "jev_side": None, "jev_confidence": None, "jev_pnl": None,
                "group": "Options solo", "delta_seconds": None, "result": opt.get("result"), "options_pnl": opt.get("pnl"),
            })
    for j in jev_rows:
        if j.get("id") in used_jev or not j.get("active") or j.get("side") not in {"CALL","PUT"}:
            continue
        comparisons.append({
            "time": j.get("time"), "symbol": j.get("symbol"), "options_side": None,
            "options_strategy": None, "options_source": "Jev", "options_evidence": None, "jev_side": j.get("side"),
            "jev_active": True, "jev_status": j.get("status"), "jev_confidence": j.get("confidence"),
            "jev_pnl": j.get("pnl"), "group": "Jev solo",
            "delta_seconds": None, "result": None, "options_pnl": None,
        })
    return sorted(comparisons, key=lambda r: r.get("time") or "")


def _group_summary(rows):
    names = ["Coinciden","Jev solo","Options solo","Direcciones opuestas","Ambos abstienen","Sin comparar"]
    out = []
    for name in names:
        group = [r for r in rows if r.get("group") == name]
        pnl = [r.get("jev_pnl") for r in group if r.get("jev_pnl") is not None]
        out.append({"group": name, "signals": len(group), "jev_closed": len(pnl), "jev_pnl": sum(float(x) for x in pnl) if pnl else 0.0})
    return out


def _confidence(rows):
    bands = [(0,.60),(.60,.65),(.65,.70),(.70,.75),(.75,.80),(.80,.90),(.90,1.01)]
    out = []
    for low, high in bands:
        group = [r for r in rows if r.get("jev_confidence") is not None and low <= float(r["jev_confidence"]) < high]
        matches = [r for r in group if r.get("group") == "Coinciden"]
        opposed = [r for r in group if r.get("group") == "Direcciones opuestas"]
        out.append({
            "band": f"{int(low*100)}–{min(100,int(high*100))}%", "signals": len(group),
            "coincide": len(matches), "opposed": len(opposed),
            "jev_pnl_when_coincide": sum(float(r.get("jev_pnl") or 0) for r in matches),
            "jev_pnl_when_opposed": sum(float(r.get("jev_pnl") or 0) for r in opposed),
        })
    return out


def _slim_summary(section):
    section = section or {}
    episodes = section.get("episodes", 0)
    if isinstance(episodes, list):
        episodes = len(episodes)
    return {"episodes": episodes, "by_candidate": section.get("by_candidate", {})}


def _live_shadow_bundle(options_root, day):
    a = Path(options_root) / "artifacts/intraday"
    meta = _load(a / "META_DECISION_LIVE_STATE_V01.json", {})
    episode = _load(a / "SIGNAL_EPISODE_LIVE_STATE_V01.json", {})

    def row_day(row):
        return str(row.get("day") or row.get("decision_date") or row.get("market_date") or row.get("time") or row.get("started_at") or "")[:10]

    decisions = [r for r in (meta.get("recent_decisions") or []) if not day or row_day(r) == day]
    decisions = sorted(decisions, key=lambda r: str(r.get("time") or ""))[-150:]
    all_episodes = list((episode.get("active_episodes") or {}).values()) + list(episode.get("recent_episodes") or [])
    episodes = [r for r in all_episodes if not day or row_day(r) == day]
    episodes = sorted(episodes, key=lambda r: str(r.get("last_observation_at") or r.get("started_at") or ""))[-150:]

    counts = {name: sum(r.get("decision") == name for r in decisions) for name in ("ACCEPT", "WAIT", "BLOCK")}
    ttt_confirmed = sum(str(r.get("ttt_state") or "").startswith("CONFIRMED") for r in episodes)
    would_authorize = sum(bool(r.get("authorization_emitted")) for r in episodes)
    return {
        "meta": {
            "version": meta.get("version"), "mode": meta.get("mode"), "live_start_utc": meta.get("live_start_utc"),
            "updated_at_utc": meta.get("updated_at_utc"), "auto_apply": meta.get("auto_apply", False),
            "broker_orders_enabled": meta.get("broker_orders_enabled", False), "latest_context": meta.get("latest_context") or {},
            "counters": meta.get("counters") or {}, "session_counts": counts, "decisions": decisions,
        },
        "episode_engine": {
            "version": episode.get("version"), "mode": episode.get("mode"), "live_start_utc": episode.get("live_start_utc"),
            "updated_at_utc": episode.get("updated_at_utc"), "auto_apply": episode.get("auto_apply", False),
            "broker_orders_enabled": episode.get("broker_orders_enabled", False), "counters": episode.get("counters") or {},
            "ttt_confirmed": ttt_confirmed, "would_authorize": would_authorize, "episodes": episodes,
        },
    }



def _meta_alpaca_bundle(options_root):
    a = Path(options_root) / "artifacts/intraday"
    broker = _load(a / "META_ALPACA_PAPER_STATE_V01.json", {})
    portfolio = _load(a / "META_PORTFOLIO_LIVE_STATE_V01.json", {})

    def number(value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    account = broker.get("account") or {}
    broker_positions = broker.get("broker_positions") or []
    open_positions = portfolio.get("open_positions") or []
    ledger = portfolio.get("live_ledger") or []
    trades = list((broker.get("trades") or {}).values())
    trades.sort(key=lambda r: str(r.get("local_exit_time") or r.get("local_entry_time") or ""))
    last_broker = trades[-1] if trades else None
    last_local = ledger[-1] if ledger else None

    policy = portfolio.get("policy") or {}
    session_date = portfolio.get("session_date")
    daily_start = number(portfolio.get("daily_start_cash"))
    portfolio_equity = number(portfolio.get("equity"))
    halt_fraction = number(policy.get("daily_loss_halt_fraction"))
    daily_pnl = portfolio_equity - daily_start if session_date and portfolio_equity is not None and daily_start is not None else None
    halt_threshold = -(daily_start * halt_fraction) if daily_start is not None and halt_fraction is not None else None
    halt_triggered = bool(
        session_date and not open_positions and daily_pnl is not None and halt_threshold is not None
        and daily_pnl <= halt_threshold
    )

    def slim_trade(row):
        if not row:
            return None
        return {k: row.get(k) for k in (
            "signal_id", "episode_id", "source", "symbol", "contract", "quantity", "status",
            "local_entry_time", "local_exit_time", "local_exit_reason", "local_net_pnl",
            "broker_exit_reason", "broker_gross_pnl", "entry_time", "exit_time", "exit_reason", "net_pnl",
        ) if k in row}

    return {
        "version": "META_ALPACA_BRIDGE_V01",
        "read_only": True,
        "available": bool(broker or portfolio),
        "broker": {
            "updated_at_utc": broker.get("updated_at_utc"),
            "submit_orders": bool(broker.get("submit_orders")),
            "paper_only": bool(broker.get("paper_only", True)),
            "market_open": broker.get("broker_market_open"),
            "reconciliation_required": bool(broker.get("reconciliation_required")),
            "status": account.get("status"),
            "equity": number(account.get("equity")),
            "cash": number(account.get("cash")),
            "buying_power": number(account.get("buying_power")),
            "options_buying_power": number(account.get("options_buying_power")),
            "options_trading_level": account.get("options_trading_level"),
            "positions": broker_positions,
            "tracked_trades": len(trades),
            "last_trade": slim_trade(last_broker),
            "last_actions": broker.get("last_actions") or [],
        },
        "portfolio": {
            "version": portfolio.get("version"),
            "mode": portfolio.get("mode"),
            "live_start_utc": portfolio.get("live_start_utc"),
            "updated_at_utc": portfolio.get("updated_at_utc"),
            "initial_cash": number(portfolio.get("initial_cash")),
            "cash": number(portfolio.get("cash")),
            "equity": portfolio_equity,
            "realized_net_pnl": number(portfolio.get("realized_net_pnl")),
            "session_date": session_date,
            "daily_start_cash": daily_start,
            "daily_pnl": daily_pnl,
            "open_positions": open_positions,
            "closed_trades": len(ledger),
            "last_trade": slim_trade(last_local),
            "daily_halt": {
                "state": "TRIGGERED" if halt_triggered else "ARMED",
                "triggered": halt_triggered,
                "loss_fraction": halt_fraction,
                "threshold_pnl": halt_threshold,
            },
            "policy": {k: policy.get(k) for k in (
                "max_global_positions", "quantity", "ranking_window_seconds", "tp_pct", "sl_pct",
                "max_horizon_minutes", "max_spread_pct", "min_abs_delta", "max_abs_delta", "min_dte", "max_dte",
            )},
        },
    }

def _sl_first_recovery_bundle(options_root):
    a = Path(options_root) / "artifacts/intraday"
    data = _load(a / "SL_FIRST_RECOVERY_STUDY_V01.json", {})
    return {
        "version": data.get("version"),
        "mode": data.get("mode"),
        "available": bool(data),
        "episode_count": data.get("episode_count", 0),
        "evaluable_count": data.get("evaluable_count", 0),
        "methodology": data.get("methodology") or [],
        "by_strategy": data.get("by_strategy") or {},
        "by_strategy_evidence": data.get("by_strategy_evidence") or {},
    }


def build_options_research(db_path, options_root, day=None):
    day = day or _today_ny()
    live = _normalize_live(options_root, day)
    jev = _jev_decisions(db_path, day)
    comparisons = _match(jev, live)
    a = Path(options_root) / "artifacts/intraday"
    h09 = _load(a / "H09_PUT_FLOW_PROSPECTIVE_V01.json", {})
    multi = _load(a / "MULTISYMBOL_DISCOVERY_V01.json", {})
    multip = _load(a / "MULTISYMBOL_PROSPECTIVE_V01.json", {})
    return {
        "version": VERSION, "read_only": True, "broker_actions_enabled": False,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(), "day": day,
        "match_window_seconds": MATCH_WINDOW_SECONDS, "symbols": SYMBOLS,
        "strategy_results": _strategy_results(options_root, day, live),
        "by_symbol": _by_symbol(options_root, live),
        "live_signals": live,
        "comparison": {"rows": comparisons, "groups": _group_summary(comparisons)},
        "confidence": _confidence(comparisons),
        "meta_live": _live_shadow_bundle(options_root, day),
        "meta_alpaca": _meta_alpaca_bundle(options_root),
        "sl_first_recovery": _sl_first_recovery_bundle(options_root),
        "h09": {
            "discovery_cutoff": h09.get("discovery_cutoff"),
            "prospective_start_after": h09.get("prospective_start_after"),
            "discovery": _slim_summary(h09.get("discovery")), "prospective": _slim_summary(h09.get("prospective")),
        },
        "multisymbol": {
            "discovery_cutoff": multi.get("discovery_cutoff"),
            "prospective_start_after": multi.get("prospective_start_after"),
            "candidates": multi.get("candidates", []), "discovery": _slim_summary(multi.get("discovery")),
            "prospective": _slim_summary(multip.get("summary")),
        },
    }
