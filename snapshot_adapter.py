"""Read-only adapter for Options-System immutable snapshot envelopes."""
import json,hashlib
from datetime import datetime

def adapt(envelope):
    payload=envelope['payload']
    canonical=json.dumps(payload,sort_keys=True,separators=(',',':'),ensure_ascii=False)
    if hashlib.sha256(canonical.encode()).hexdigest()!=envelope['sha256']:
        raise ValueError('Snapshot checksum mismatch')
    timestamp=envelope['captured_at_utc']
    captured=datetime.fromisoformat(timestamp)
    if captured.tzinfo is None:raise ValueError('Timezone missing')
    states=[];quotes=[]
    for symbol,record in payload['symbols'].items():
        stock=record.get('stock_snapshot') or {}
        contracts=[]
        for name,option in (record.get('option_snapshot') or {}).get('snapshots',{}).items():
            quote=option.get('latestQuote') or {}
            bid,ask=quote.get('bp'),quote.get('ap')
            qt=quote.get('t')
            if not qt or bid is None or ask is None:continue
            quote_time=datetime.fromisoformat(qt.replace('Z','+00:00'))
            if quote_time>captured:continue
            # OCC suffix has C/P exactly 9 characters before the end.
            side={'C':'CALL','P':'PUT'}.get(name[-9:-8])
            if not side:continue
            contracts.append(dict(symbol=name,side=side,bid=bid,ask=ask,timestamp=qt,volume=(option.get('dailyBar') or {}).get('v',0)))
            quotes.append(dict(symbol=name,timestamp=qt,bid=bid))
        # Baseline decisions and outcomes are never forwarded.
        features={'spot':record.get('spot')}
        for key in ('minuteBar','dailyBar','prevDailyBar','latestTrade','latestQuote'):
            item=stock.get(key)
            if not isinstance(item,dict):continue
            item=dict(item)
            raw_time=item.get('t')
            if raw_time:
                try:
                    if datetime.fromisoformat(raw_time.replace('Z','+00:00'))>captured:continue
                except (ValueError,TypeError):continue
            features[key]=item
        states.append(dict(timestamp=timestamp,symbol=symbol,features=features,contracts=contracts))
    return states,quotes,payload.get('market_clock',{}).get('is_open',False)
