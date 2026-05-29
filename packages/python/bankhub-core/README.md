# bankhub-core

The core of [bankhub](https://github.com/latetedemelon/banker): the normalised
`Transaction` model, the source/destination plugin registry, the
ingest → dedup → deliver engine, the idempotency store, the account-mapping
layer, and the `bankhub` CLI.

This package contains **no adapters** — they ship separately and register
themselves via the `bankhub.plugins` entry point:

- **bankhub-files** — CSV / OFX / QIF / MT940 / CAMT / PDF sources + CSV / JSON destinations.
- **bankhub-connectors** — Plaid, SimpleFIN, Yodlee, Lunchmoney, YNAB, Actual, …

Most users install the umbrella **bankhub** (`pip install bankhub`) rather than
this package directly.

```python
import bankhub

src = bankhub.build_source("ofx", file="statement.qfx")
for txn in src.fetch():           # amount is signed: negative = money out
    print(txn.date, txn.amount, txn.payee)
```

The stable public API is everything re-exported from the top-level `bankhub`
package (`Transaction`, `Source`, `Destination`, `Engine`, `Store`,
`AccountMap`, `build_source`/`build_destination`, the `register_*` decorators,
the error types, …).
