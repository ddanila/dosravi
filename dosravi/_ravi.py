"""Prefer the pinned source dependency; installed wheels use their declared dependency."""

import sys
from pathlib import Path


def require():
    source = Path(__file__).resolve().parents[1] / "third_party/ravi/src"
    if (source.parents[2] / ".gitmodules").is_file() and not (
        source / "ravi/__init__.py"
    ).is_file():
        raise ImportError(
            "RAVI submodule missing: run git submodule update --init third_party/ravi"
        )
    if (source / "ravi/__init__.py").is_file():
        sys.path.insert(0, str(source))
    try:
        import ravi
    except ImportError as error:
        raise ImportError(
            "RAVI is missing: run git submodule update --init third_party/ravi "
            "or install DOSRAVI with its declared dependencies"
        ) from error
    if (source / "ravi/__init__.py").is_file() and not Path(
        ravi.__file__
    ).resolve().is_relative_to(source):
        raise ImportError(
            "Another RAVI source is already imported; start a fresh process using the pinned dependency"
        )
    if ravi.__version__ != "0.1.0":
        raise ImportError(f"DOSRAVI requires ravi-core 0.1.0, found {ravi.__version__}")
