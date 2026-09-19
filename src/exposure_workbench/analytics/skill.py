"""The measures, under the name they had until V1.

Everything that was here has a home now. The METHODS and their readings are
analytics/registry — one entry, three faces. The fourteen DOMAINS, the desk rules
and the roster are analytics/handbook: three chapters cut by resource family, six
sections each, rendered from the registry where the registry knows. The domains'
programs went with the program language they were written in (tools/primitives).

What remains is this re-export, so a reader that says `skill.METHODS` reads the
registry's own objects and not a second copy.
"""

from __future__ import annotations

from exposure_workbench.analytics.registry import (  # noqa: F401
    EXECUTORS, METHODS, RANK_OP, REGRESS_OP, SCALAR_OPS, SCALE_OP, SUBJECT_KINDS,
    Method, method_for_yield, methods_for, nearest,
)
