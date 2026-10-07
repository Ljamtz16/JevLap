"""Read-only adapter for Options-System immutable snapshot envelopes."""
import json,hashlib
from datetime import datetime

def intraday_view(payload):
    """Normalize layout only, preserving the original capture and payload hash."""
    if 'symbols' in payload:
        return payload
    if payload.get('underlying', {}).get('symbol') != 'SPY':
        raise ValueError('Unsupported canonical underlying')
    stock=payload['underlying']['snapshot']
    trade=stock.get('latestTrade') or {}; quote=stock.get('latestQuote') or {}
    spot=trade.get('p') or (((quote.get('bp') or 0)+(quote.get('ap') or 0))/2)
    clock=payload['market_clock']
    from zoneinfo import ZoneInfo
    market_date=datetime.fromisoformat(clock['timestamp'].replace('Z','+00:00')).astimezone(ZoneInfo('America/New_York')).date().isoformat()
    return dict(market_date=market_date, market_clock=clock,
                global_context=dict(cross_market=(payload.get('cross_market') or {}).get('features') or {}),
                symbols={'SPY':dict(spot=spot,stock_snapshot=stock,option_snapshot=payload['options']['snapshot'])})


def adapt(envelope):
    payload=envelope['payload']
    canonical=json.dumps(payload,sort_keys=True,separators=(',',':'),ensure_ascii=False)
    if hashlib.sha256(canonical.encode()).hexdigest()!=envelope['sha256']:
        raise ValueError('Snapshot checksum mismatch')
    timestamp=envelope['captured_at_utc']
    captured=datetime.fromisoformat(timestamp)
    if captured.tzinfo is None:raise ValueError('Timezone missing')
    payload=intraday_view(payload)
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
            bar=option.get('dailyBar') or {}
            if bar.get('t') and datetime.fromisoformat(bar['t'].replace('Z','+00:00'))>captured:bar={}
            contracts.append(dict(symbol=name,side=side,bid=bid,ask=ask,timestamp=qt,volume=bar.get('v'),
                                  bid_size=quote.get('bs'),ask_size=quote.get('as'),
                                  delta=(option.get('greeks') or {}).get('delta')))
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
        state=dict(timestamp=timestamp,symbol=symbol,features=features,contracts=contracts,snapshot_sha256=envelope['sha256'],capture_id=envelope.get('capture_id'))
        close=payload.get('market_clock',{}).get('next_close')
        if close:
            from zoneinfo import ZoneInfo
            ct=datetime.fromisoformat(close.replace('Z','+00:00'))
            if ct.tzinfo is None:raise ValueError('Close timezone missing')
            if ct.astimezone(ZoneInfo('America/New_York')).date()==captured.astimezone(ZoneInfo('America/New_York')).date():
                state['session_close_at_utc']=close
        states.append(state)
    return states,quotes,payload.get('market_clock',{}).get('is_open',False)
