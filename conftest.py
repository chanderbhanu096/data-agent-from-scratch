"""Shared pytest setup.

Every chapter has its own `run.py` — that's deliberate, since `python
chapters/NN_name/run.py` is how you run one. But it means plain `import run`
from a test resolves to whichever chapter pytest collected first.

`load_run()` sidesteps that by loading the `run.py` next to the calling test
under a unique module name.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def load_run(test_file: str) -> ModuleType:
    """Import the run.py beside `test_file`. Pass `__file__` from your test."""
    chapter_dir = Path(test_file).resolve().parent
    run_path = chapter_dir / "run.py"
    module_name = f"chapter_{chapter_dir.name}_run"

    if module_name in sys.modules:
        return sys.modules[module_name]

    spec = importlib.util.spec_from_file_location(module_name, run_path)
    if spec is None or spec.loader is None:  # pragma: no cover
        raise ImportError(f"could not load {run_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module
