"""Compatibility import for ravi.backends.dos.client; implementation lives in RAVI."""

import importlib
import sys

from ._ravi import require

require()
sys.modules[__name__] = importlib.import_module("ravi.backends.dos.client")
