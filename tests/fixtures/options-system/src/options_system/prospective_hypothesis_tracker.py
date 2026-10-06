import json,csv
from pathlib import Path

def _f(x):
    try:return float(x)
    except (TypeError,ValueError):return None

def load_hypotheses(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))["hypotheses"]

def _compare(v, op, t):
    if op in (">", "gt"):
        return v > t
    if op in (">=", "gte"):
        return v >= t
    if op in ("<", "lt"):
        return v < t
    if op in ("<=", "lte"):
        return v <= t
    if op in ("==", "eq"):
        return v == t
    raise ValueError(f"Unsupported rule op: {op}")

def hypothesis_active(h,row):
    r=h["rules"]
    checks=[]

    # Generic rule format used by frozen candidates promoted from discovery:
    # [{"feature": "iwm_from_open", "op": "<=", "value": -0.0033}, ...]
    if isinstance(r, list):
        for rule in r:
            v=_f(row.get(rule["feature"]))
            t=float(rule["value"])
            checks.append(v is not None and _compare(v, rule["op"], t))
        return all(checks)

    # Legacy fixed-key format used by H01/H02.
    mapping={
      "d_atm_iv_prev_gt":("d_atm_iv_prev",lambda v,t:v>t),
      "d_put_call_iv_skew_prev_lt":("d_put_call_iv_skew_prev",lambda v,t:v<t),
      "d_put_call_volume_ratio_1pct_prev_gt":("d_put_call_volume_ratio_1pct_prev",lambda v,t:v>t),
      "put_call_iv_skew_gt":("put_call_iv_skew",lambda v,t:v>t),
      "put_call_volume_ratio_1pct_lt":("put_call_volume_ratio_1pct",lambda v,t:v<t)
    }
    for key,threshold in r.items():
        field,fn=mapping[key];v=_f(row.get(field))
        checks.append(v is not None and fn(v,float(threshold)))
    return all(checks)

def annotate(rows,hypotheses):
    out=[]
    for r in rows:
        x=dict(r)
        active=[h["id"] for h in hypotheses if hypothesis_active(h,r)]
        x["active_hypotheses"]=";".join(active)
        out.append(x)
    return out

def write_tracker(rows,out_csv):
    if not rows:return 0
    fields=[]
    for r in rows:
        for k in r:
            if k not in fields:fields.append(k)
    Path(out_csv).parent.mkdir(parents=True,exist_ok=True)
    with open(out_csv,"w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
    return len(rows)

def summarize(rows,hypotheses):
    report={}
    for h in hypotheses:
        hid=h["id"];side=h["side"];hz=h["horizon_min"]
        ret_key=f"{side}_ret_{hz}m"
        hit=[r for r in rows if hid in (r.get("active_hypotheses") or "").split(";") and _f(r.get(ret_key)) is not None]
        vals=[_f(r.get(ret_key)) for r in hit]
        mfe=[_f(r.get(f"{side}_mfe_{hz}m")) for r in hit]
        mae=[_f(r.get(f"{side}_mae_{hz}m")) for r in hit]
        mfe=[v for v in mfe if v is not None];mae=[v for v in mae if v is not None]
        touch=[r.get(f"{side}_{hz}m_tp10_sl10") for r in hit]
        decided=[v for v in touch if v in ("TP_FIRST","SL_FIRST")]
        report[hid]={"n":len(vals),"mean_return":sum(vals)/len(vals) if vals else None,
                     "win_rate":sum(v>0 for v in vals)/len(vals) if vals else None,
                     "gt10_rate":sum(v>=.10 for v in vals)/len(vals) if vals else None,
                     "ltm10_rate":sum(v<=-.10 for v in vals)/len(vals) if vals else None,
                     "mean_mfe":sum(mfe)/len(mfe) if mfe else None,
                     "mean_mae":sum(mae)/len(mae) if mae else None,
                     "tp10_before_sl10_rate":sum(v=="TP_FIRST" for v in decided)/len(decided) if decided else None,
                     "tp10_sl10_decided_n":len(decided)}
    return report

