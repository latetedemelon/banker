# -*- coding: utf-8 -*-
"""bankhub-files -- file-format adapters for bankhub.

Importing this package registers its sources (CSV, OFX, QIF, MT940, CAMT, PDF)
and destinations (CSV, JSON) with the bankhub plugin registry.  bankhub loads
it automatically via the ``bankhub.plugins`` entry point, so you normally don't
import it directly -- use ``bankhub.build_source("ofx", ...)`` and friends.
"""

from . import destinations, sources  # noqa: F401  (imported for side effects)

__version__ = "0.4.0"
