# -*- coding: utf-8 -*-
"""bankhub-connectors -- API / aggregator adapters for bankhub.

Importing this package registers its sources (Plaid, SimpleFIN, Yodlee,
GoCardless, TrueLayer, MX, Finicity, Teller, Salt Edge, Flinks, Lunchmoney)
and destinations (Lunchmoney, YNAB, Actual) with the bankhub plugin registry.
bankhub loads it automatically via the ``bankhub.plugins`` entry point; use
``bankhub.build_source("plaid", ...)`` and friends rather than importing here.
"""

from . import destinations, sources  # noqa: F401  (imported for side effects)

__version__ = "0.4.0"
