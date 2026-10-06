"""Read-only check and pin dedicated paper account. Does not submit orders."""
import json,os,shlex
from pathlib import Path
from paper_executor import PaperAPI,ROOT,now
from credentials import load

def main():
    load()
    path=Path.home()/'.config/jev-lab/credentials.env'
    original=path.read_text(encoding='utf-8') if path.exists() else ''
    for line in original.splitlines():
        if not line.strip() or line.lstrip().startswith('#'):continue
        name,sep,value=line.partition('=')
        if sep and name in ('TYPESAFE_API_KEY','ALPACA_PAPER_API_KEY','ALPACA_PAPER_SECRET_KEY'):
            parts=shlex.split(value)
            if len(parts)!=1:raise ValueError('Invalid environment field')
            os.environ[name]=parts[0]
    api=PaperAPI();account=api.request('/v2/account')
    if account['status']!='ACTIVE' or account.get('trading_blocked'):raise ValueError('Account unavailable for paper trading')
    positions=api.request('/v2/positions');orders=api.request('/v2/orders?status=open&limit=500')
    if positions or orders:raise ValueError('Dedicated paper account must initially have no positions or open orders')
    ROOT.joinpath('data').mkdir(exist_ok=True)
    identity={'account_id':account['id'],'equity':account['equity'],'checked_at':now().isoformat()}
    (ROOT/'data/paper-account.json').write_text(json.dumps(identity),encoding='utf-8')
    if path.exists():
        lines=[s for s in original.splitlines() if not s.startswith(('JEV_PAPER_ACCOUNT_ID=','JEV_PAPER_ENABLED='))]
        lines.extend(['JEV_PAPER_ACCOUNT_ID='+account['id'],'JEV_PAPER_ENABLED=false'])
        path.write_text('\n'.join(lines)+'\n',encoding='utf-8');path.chmod(0o600)
    print(json.dumps({'paper':'VERIFIED','equity':account['equity'],'options_trading_level':account.get('options_trading_level'),'positions':len(positions),'open_orders':len(orders),'orders_enabled':False,'account_pin_saved':path.exists()}))
if __name__=='__main__':main()
