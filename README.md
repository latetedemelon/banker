# banker

A universal hub for personal-finance data: ingest transactions from any
*source* (CSV/OFX/QIF/MT940/CAMT/Excel statements, PDF, Plaid, SimpleFIN,
Yodlee, GoCardless, TrueLayer, MX, Finicity, Teller, Salt Edge, Stripe,
Lunchmoney …), normalise them into one model, de-duplicate, and deliver them to
any *destination* (Lunchmoney, YNAB, Actual Budget, Firefly III, PocketSmith,
OFX/QFX for Quicken·Simplifi·GnuCash, Copilot/Tiller CSV, Excel, CSV, JSON …).
One ingest fans out to many destinations, and every run is idempotent.

banker is both an **app** (a CLI / Docker image you run) and a **library** you
embed. It's heading toward parity in **Python and Node** over a shared,
language-neutral adapter spec, so a provider is described once and both
runtimes use it.

## Repository layout

This is a monorepo.

| Path | What |
| --- | --- |
| [`packages/python/`](packages/python/) | The Python library + CLI (`bankhub`), the reference implementation. Start here — see its [README](packages/python/README.md). |
| [`spec/`](spec/) | *(planned)* The shared, language-neutral adapter spec — the normalised `Transaction` schema, provider field-maps, and sign rules — that Python and the future Node port both consume. |
| `packages/node/` | *(planned)* The Node port, validated against the same spec. |

## Quick start

```bash
cd packages/python
pip install .            # core; add [connectors], [pdf], [actual], or [all]
bankhub --help
```

Full install options, the library API, the CLI, and how to write an adapter
are documented in the [Python package README](packages/python/README.md).

## Design log

Architectural decisions and the app/library + cross-language direction are
recorded in [DECISIONS.md](DECISIONS.md).

## Docker

```bash
docker build -t banker packages/python   # build context is the Python package
docker run --rm banker --help
```

## Security

See [SECURITY.md](SECURITY.md).
