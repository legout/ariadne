#!/usr/bin/env python
"""Thin shim: the promotion logic lives in :mod:`ariadne.promote`.

Kept so ``python scripts/promote.py`` (demo.sh, README paths) keeps working.
"""

from ariadne.promote import main

if __name__ == "__main__":
    raise SystemExit(main())
