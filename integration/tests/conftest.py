"""Import wiring for the paired Core/SDK scenarios (spec 0031 §4).

These modules reuse Core-native authoring/contract helpers
(``tests.test_contracts``, ``tests.test_git_authoring``) from the Core
member's own test tree. The member directory is inserted deliberately here
instead of relying on incidental sys.path state; the member's ``tests``
directory is a namespace portion, so its helper modules resolve without
copying any fixture tree. The paired modules themselves import each other
explicitly as ``integration.tests.lumio_metric_mvp``.
"""

from __future__ import annotations

import sys
from pathlib import Path

CORE_MEMBER = (
    Path(__file__).resolve().parents[2]
    / "products"
    / "ariadne"
    / "packages"
    / "ariadne-data"
)
if str(CORE_MEMBER) not in sys.path:
    sys.path.insert(0, str(CORE_MEMBER))
