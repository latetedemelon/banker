# Canonical adapter registry

The cross-runtime list of adapter `name`s, their owning distribution, and the
optional dependency each needs. A port (Node, …) should register the same names
with comparable options so pipelines are portable. Generated from `bankhub`
0.4.x — **20 sources, 12 destinations**. Per-adapter options live in each
adapter's own docstring (the source of truth).

## Sources (20)

### File formats — `bankhub-files`

| name | needs | reads |
| --- | --- | --- |
| `csv` | — | delimited statements, data-driven per-bank profiles (`data/banks.yml`) |
| `ofx` | — | OFX 1.x (SGML) and 2.x (XML) / QFX |
| `qif` | — | Quicken Interchange Format |
| `mt940` | — | SWIFT MT940 |
| `camt` | — | ISO 20022 CAMT.053 (SEPA) |
| `pdf` | `pdfplumber` | PDF statements via table extraction (`data/pdf_banks.yml`) |
| `xlsx` | `openpyxl` | Excel `.xlsx` statements |

### Aggregators / APIs — `bankhub-connectors` (all need `requests`)

| name | coverage |
| --- | --- |
| `plaid` | US/CA/EU (`/transactions/sync`) |
| `simplefin` | SimpleFIN Bridge (privacy-friendly, read-only) |
| `yodlee` | global |
| `gocardless` | EU/UK open banking (ex-Nordigen, free) |
| `truelayer` | UK/EU |
| `mx` | US |
| `finicity` | US (Mastercard) |
| `teller` | US |
| `saltedge` | global |
| `flinks` | Canada |
| `stripe` | Stripe Financial Connections (bank data) |
| `stripe_payments` | Stripe balance transactions (merchant activity) |
| `lunchmoney` | pull back from Lunchmoney (reconciliation) |

## Destinations (12)

### File formats — `bankhub-files`

| name | needs | writes |
| --- | --- | --- |
| `csv` | — | CSV export/archive |
| `json` | — | line-delimited JSON |
| `xlsx` | `openpyxl` | Excel `.xlsx` |
| `ofx` | — | OFX/QFX import file (Quicken / Quicken Simplifi / GnuCash) |
| `copilot` | — | Copilot Money import CSV |
| `tiller` | — | Tiller Transactions-sheet CSV |
| `gnucash` | `piecash` | native GnuCash SQLite book |

### Apps / APIs — `bankhub-connectors`

| name | needs | target |
| --- | --- | --- |
| `lunchmoney` | `requests` | Lunchmoney |
| `ynab` | `requests` | YNAB (milliunits, `import_id` dedup) |
| `firefly` | `requests` | Firefly III (self-hosted) |
| `pocketsmith` | `requests` | PocketSmith |
| `actual` | `actualpy` | Actual Budget (self-hosted) |

> Maturity: the file formats and the longest-standing connectors are
> exercised by the test suite; several API adapters are built from official
> docs and unit-tested at the transform level but **not yet live-certified**.
> See `../DECISIONS.md`.
