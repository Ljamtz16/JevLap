"""Versioned source routing: SPY shares Options' exact prospective capture."""
from pathlib import Path
import os
import re
from zoneinfo import ZoneInfo
from session_policy import stamp

COMMON_START_DATE = os.getenv('JEV_COMMON_SNAPSHOT_START_DATE', '2026-10-07')


def snapshot_paths(source, canonical_source=None):
    source = Path(source)
    canonical = Path(canonical_source) if canonical_source else source.parent/'prospective'
    paths = [(p, 'INTRADAY_LEGACY') for p in source.glob('intraday_options_*.json')]
    paths += [(p, 'SPY_PROSPECTIVE_CANONICAL_V1') for p in canonical.glob('spy_options_*.json')]
    def order(item):
        match = re.search(r'\d{8}T\d{6}', item[0].name)
        return (match.group(0) if match else item[0].name, item[0].name)
    return sorted(paths, key=order)


def allowed_symbols(envelope, source_kind, start_date=COMMON_START_DATE):
    day = stamp(envelope['captured_at_utc']).astimezone(ZoneInfo('America/New_York')).date().isoformat()
    if source_kind == 'SPY_PROSPECTIVE_CANONICAL_V1':
        return {'SPY'} if day >= start_date else set()
    symbols = set(envelope['payload'].get('symbols', {}))
    if day >= start_date:
        symbols.discard('SPY')
    return symbols
