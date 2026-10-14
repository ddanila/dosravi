"""Compatibility import for ravi.protocols.dos_v1; implementation lives in RAVI."""

import importlib
import sys

from ._ravi import require

require()
sys.modules[__name__] = importlib.import_module("ravi.protocols.dos_v1")
