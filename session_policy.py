"""Session boundaries for research replay. Never invent an expiry settlement."""
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

NY = ZoneInfo('America/New_York')
SIMULATION_VERSION = 'intraday_session_v2'


def stamp(value):
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('Timestamp requiere zona horaria')
    return parsed


def session_bounds(snapshot):
    entry = stamp(snapshot['timestamp'])
    day = entry.astimezone(NY).date()
    start = datetime.combine(day, time(9, 30), NY)
    close = datetime.combine(day, time(16), NY)
    supplied = snapshot.get('session_close_at_utc')
    if supplied:
        close = stamp(supplied)
        if close.astimezone(NY).date() != day or close <= start:
            raise ValueError('Cierre de sesión incompatible')
    return start, close


def expiry_day(contract):
    suffix = contract[-15:-9]
    try:
        return date(2000 + int(suffix[:2]), int(suffix[2:4]), int(suffix[4:6])) if len(suffix) == 6 else None
    except ValueError:
        return None
