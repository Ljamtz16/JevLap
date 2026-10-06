import math,re
from datetime import datetime,date

_OCC=re.compile(r"^([A-Z]+)(\d{6})([CP])(\d{8})$")

def _median(xs):
 xs=sorted(float(x) for x in xs if x is not None and math.isfinite(float(x)))
 if not xs:return None
 n=len(xs);m=n//2
 return xs[m] if n%2 else (xs[m-1]+xs[m])/2

def _parse_symbol(sym):
 m=_OCC.match(sym)
 if not m:return None
 root,ds,cp,strike=m.groups()
 exp=datetime.strptime(ds,"%y%m%d").date()
 return {"root":root,"expiration":exp,"side":"call" if cp=="C" else "put","strike":int(strike)/1000.0}

def extract_chain_features(chain_snapshot,spot,market_date):
 snaps=(chain_snapshot or {}).get("snapshots",{})
 rows=[]
 for sym,s in snaps.items():
  meta=_parse_symbol(sym)
  if not meta:continue
  q=s.get("latestQuote") or {}; b=q.get("bp"); a=q.get("ap")
  mid=None; spread=None; spread_pct=None
  if b is not None and a is not None and a>=b and (a+b)>0:
   mid=(a+b)/2; spread=a-b; spread_pct=spread/mid if mid>0 else None
  g=s.get("greeks") or {}; bar=s.get("dailyBar") or {}
  rows.append({**meta,"symbol":sym,"iv":s.get("impliedVolatility"),"bid":b,"ask":a,"mid":mid,
    "spread":spread,"spread_pct":spread_pct,"volume":bar.get("v"),
    "delta":g.get("delta"),"gamma":g.get("gamma"),"theta":g.get("theta"),"vega":g.get("vega"),
    "dte":(meta["expiration"]-market_date).days,
    "moneyness":meta["strike"]/spot-1 if spot else None})
 near=[r for r in rows if abs(r["moneyness"])<=.01 and 1<=r["dte"]<=10]
 calls=[r for r in near if r["side"]=="call"]; puts=[r for r in near if r["side"]=="put"]
 call_iv=_median([r["iv"] for r in calls]); put_iv=_median([r["iv"] for r in puts])
 call_vol=sum((r["volume"] or 0) for r in calls); put_vol=sum((r["volume"] or 0) for r in puts)
 total_vol=call_vol+put_vol
 return {
  "contract_count":len(rows),"near_atm_count":len(near),
  "atm_iv":_median([r["iv"] for r in near]),
  "call_iv_1pct":call_iv,"put_iv_1pct":put_iv,
  "put_call_iv_skew":(put_iv-call_iv) if put_iv is not None and call_iv is not None else None,
  "median_spread_pct_1pct":_median([r["spread_pct"] for r in near]),
  "call_volume_1pct":call_vol,"put_volume_1pct":put_vol,
  "put_call_volume_ratio_1pct":(put_vol/call_vol) if call_vol>0 else None,
  "put_volume_share_1pct":(put_vol/total_vol) if total_vol>0 else None,
  "median_abs_delta_1pct":_median([abs(r["delta"]) for r in near if r["delta"] is not None]),
  "median_gamma_1pct":_median([r["gamma"] for r in near]),
  "median_vega_1pct":_median([r["vega"] for r in near]),
 }

