"""Use Options-System's exact selector for new Jev and Comparator simulations."""
import importlib.util
import os
from pathlib import Path
from functools import lru_cache


@lru_cache(maxsize=4)
def load_selector(root):
    path = root / 'src/options_system/executable_contracts.py'
    spec = importlib.util.spec_from_file_location('shared_executable_contracts', path)
    if spec is None or spec.loader is None:
        raise ValueError('Shared contract selector unavailable')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.select_contract


def select_contract(*args, **kwargs):
    root = Path(os.getenv('OPTIONS_SYSTEM_ROOT', str(Path(__file__).resolve().parent.parent / 'options-system')))
    selector = load_selector(root)
    unbounded = bool(kwargs.pop('unbounded_budget', False))
    if not unbounded:
        return selector(*args, **kwargs)

    contracts = args[0] if args else kwargs.get('contracts', [])
    quantity = int(kwargs.get('quantity', 1))
    asks = []
    for row in contracts:
        try:
            ask = float(row.get('ask'))
        except (TypeError, ValueError):
            continue
        if ask > 0:
            asks.append(ask)
    # Non-binding budget derived only from the captured chain. This keeps DTE,
    # delta, spread, liquidity and quote-freshness filters intact while removing
    # affordability/max-premium as research-selection constraints.
    max_ask = max(asks, default=1.0)
    forwarded = list(args)
    if len(forwarded) >= 6:
        forwarded[4] = max_ask * 100 * quantity
        forwarded[5] = 1.0
    else:
        kwargs['cash'] = max_ask * 100 * quantity
        kwargs['risk_fraction'] = 1.0
    policy = dict(kwargs.get('policy') or {})
    policy['max_contract_price'] = max_ask
    kwargs['policy'] = policy
    result = selector(*forwarded, **kwargs)
    result['budget_mode'] = 'UNBOUNDED_RESEARCH'
    result['cash'] = None
    result['risk_fraction'] = None
    result['premium_budget'] = None
    result['policy'] = dict(result.get('policy') or {})
    result['policy']['max_contract_price'] = None
    return result
