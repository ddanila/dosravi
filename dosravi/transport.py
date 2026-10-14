"""Compatibility import for ravi.transport; implementation lives in RAVI."""

import importlib
import sys

from ._ravi import require

require()
sys.modules[__name__] = importlib.import_module("ravi.transport")
