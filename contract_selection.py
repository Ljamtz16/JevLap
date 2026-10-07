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
    return load_selector(root)(*args, **kwargs)
