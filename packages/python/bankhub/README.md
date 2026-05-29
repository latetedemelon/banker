# banker — a universal hub for personal-finance data

**banker** ingests transactions from any *source* (CSV statements, Plaid,
Flinks, Lunchmoney …), normalises them into one model, de-duplicates them, and
delivers them to any *destination* (Lunchmoney, YNAB, Actual Budget, CSV,
JSON …). One ingest can fan out to many destinations, and every run is
idempotent — nothing is ever imported or pushed twice.

```
 SOURCES                         CORE                         DESTINATIONS
┌───────────┐         ┌──────────────────────────┐         ┌──────────────┐
│ CSV        │──┐     │  normalise → dedup store   │     ┌──▶│ Lunchmoney   │
│ Plaid      │──┤     │  → account mapping         │     │   │ YNAB         │
│ Flinks     │──┼────▶│                            │─────┼──▶│ Actual       │
│ Lunchmoney │──┤     │   (one ingest, many        │     │   │ CSV / JSON   │
│ …          │──┘     │    idempotent deliveries)  │     └──▶│ …            │
└───────────┘         └──────────────────────────┘         └──────────────┘
```

> This is **v2**. It grew out of a CSV→Lunchmoney sync script (still present
> under `lib/`, see [Legacy](#legacy)). v2 generalises that idea into a
> pluggable hub and removes the original `eval`-based CSV parser.

## Why

Every personal-finance tool speaks its own dialect. Aggregators (Plaid,
Flinks) pull raw data; budgeting apps (Lunchmoney, YNAB, Actual) want it
pushed in. banker is the translation layer in the middle: write an adapter
once and any source can feed any destination.

## Concepts

| Concept | What it is |
| --- | --- |
| **Transaction** | The canonical model every adapter speaks (`bankhub/models.py`). Amount is signed: **negative = money out**. |
| **Source** | An input adapter that yields `Transaction`s (`bankhub/sources/`). |
| **Destination** | An output adapter that delivers `Transaction`s (`bankhub/destinations/`). |
| **Store** | SQLite dedup + per-destination sync state (`bankhub/store.py`). This is what makes re-runs idempotent. |
| **AccountMap** | Maps a source account id to a destination account id (`bankhub/mapping.py`). |
| **Engine** | Orchestrates source → store → mapping → destinations (`bankhub/engine.py`). |
| **Pipeline** | A declarative YAML wiring of sources to destinations (`bankhub/config.py`). |

### Supported adapters

**Sources — bank file formats** (pure Python, no extra deps):

| Source | Format |
| --- | --- |
| `csv` | delimited statements (data-driven per-bank profiles) |
| `ofx` | OFX 1.x (SGML) and 2.x (XML) |
| `qif` | Quicken Interchange Format |
| `mt940` | SWIFT MT940 statements |
| `camt` | ISO 20022 CAMT.053 (SEPA) |
| `pdf` | PDF statements via table extraction (needs `pdfplumber`) |

**Sources — aggregators / APIs** (need `requests` + credentials):

| Source | Coverage |
| --- | --- |
| `plaid` | US/CA/EU |
| `flinks` | Canada |
| `simplefin` | SimpleFIN Bridge (privacy-friendly) |
| `gocardless` | EU/UK open banking (ex-Nordigen, free) |
| `truelayer` | UK/EU |
| `yodlee` | global |
| `mx` | US |
| `finicity` | US (Mastercard) |
| `teller` | US |
| `saltedge` | global |
| `lunchmoney` | pull back from Lunchmoney |

**Destinations:**

| Destination | Needs |
| --- | --- |
| `csv`, `json` | — |
| `lunchmoney`, `ynab` | `requests` |
| `actual` | `actualpy` |

Every source emits the same normalised `Transaction`, so **any** source above
can feed **any** destination. Don't see your bank? Most are one YAML profile
(file formats) or ~80 lines (a new API) — see [Extending](#extending-add-an-adapter).

## Install

`bankhub` ships as a small family of packages (PyPI release pending):

| Package | Provides |
| --- | --- |
| **bankhub** | Umbrella install: the core + all file-format adapters (batteries-included). |
| **bankhub-core** | The engine, model, registry, idempotency store, and `bankhub` CLI. Importable as `bankhub`. |
| **bankhub-files** | CSV/OFX/QIF/MT940/CAMT/PDF sources + CSV/JSON destinations. |
| **bankhub-connectors** | Plaid, SimpleFIN, Yodlee, Lunchmoney, YNAB, Actual, … (HTTP integrations). |

```bash
pip install bankhub                # core + CLI + every file-format adapter
pip install "bankhub[connectors]"  # + Plaid, SimpleFIN, Lunchmoney, YNAB, …
pip install "bankhub[all]"         # everything, incl. optional pdfplumber + actualpy
```

The adapter packages register themselves with the core via the `bankhub.plugins`
entry point — install one and `bankhub.build_source(...)` / the CLI pick it up
automatically. Installing provides a `bankhub` command (the same CLI as
`python main.py`).

Developing in this repo? Install the workspace editable, core first:

```bash
cd packages/python
pip install -e ./bankhub-core
pip install -e ./bankhub-files ./bankhub-connectors
```

## Quickstart

Sync a downloaded Revolut statement to Lunchmoney **and** archive it as CSV:

```bash
export LUNCHMONEY_TOKEN=xxxx
python main.py sync \
  --source csv --source-opt bank=revolut --source-opt file=revolut.csv \
  --dest lunchmoney \
  --dest csv --dest-opt csv.file=archive/revolut.csv \
  --account-map config/accounts.yml
```

Run it again tomorrow with an updated statement — only new rows are imported,
and only new rows are pushed to each destination.

### Use as a library

Everything the CLI does is available through a small, stable public API
(everything re-exported from the top-level `bankhub` package):

```python
import bankhub

# 1. Build a source and read normalised transactions (no store needed):
src = bankhub.build_source("ofx", file="statement.qfx")
for txn in src.fetch():
    print(txn.date, txn.amount, txn.payee)   # amount is signed: -ve = outflow

# 2. Or run the full hub: ingest -> dedup -> deliver, idempotently.
store = bankhub.Store("db/bankhub.db")
engine = bankhub.Engine(store, bankhub.AccountMap.from_file("config/accounts.yml"))
report = engine.sync(
    bankhub.build_source("simplefin"),                 # reads $SIMPLEFIN_ACCESS_URL
    [bankhub.build_destination("lunchmoney", token="..."),
     bankhub.build_destination("json", file="out.jsonl")],
)
print(report.ingest, report.deliveries)

bankhub.available_sources()        # -> ['camt', 'csv', 'finicity', 'flinks', ...]
bankhub.available_destinations()   # -> ['actual', 'csv', 'json', 'lunchmoney', 'ynab']
```

`Transaction`, `Source`, `Destination`, `Engine`, `Store`, `AccountMap`,
`build_source`/`build_destination`, the `register_*` decorators and the error
types are all importable from `bankhub` directly.

### CLI

```
python main.py --help

  sources                List available source adapters
  destinations           List available destination adapters
  sync                   Ingest from one source, deliver to many destinations
  run CONFIG             Run every pipeline defined in a YAML file
  accounts               List accounts exposed by a source (if supported)
  stats                  Show ingested / delivered counts
  data-import            [legacy] import a bank CSV into the store
  data-export            [legacy] push not-yet-synced transactions to Lunchmoney
  lunchmoney-id          [legacy] reconcile Lunchmoney ids back into the store
```

Pass adapter options with `--source-opt key=value` and `--dest-opt key=value`.
With multiple destinations, scope an option to one with `--dest-opt name.key=value`
(a bare `key=value` applies to all destinations).

`--dry-run` reports exactly what *would* happen and writes nothing.

### Pipelines

For anything beyond one source, describe the whole hub in YAML and run it with
one command. See [`pipeline.example.yml`](pipeline.example.yml):

```yaml
store: db/bankhub.db
account_map: config/accounts.yml
pipelines:
  - name: revolut-csv
    source: {type: csv, bank: revolut, file: ~/statements/revolut.csv}
    destinations:
      - {type: lunchmoney, token: "${LUNCHMONEY_TOKEN}"}
      - {type: csv, file: exports/revolut.csv}
```

```bash
python main.py run pipeline.example.yml
```

`${VAR}` is expanded from the environment, so tokens never live in the file.

### Account mapping

Source accounts rarely share ids with your budgeting app. Map them per
destination — see [`config/accounts.example.yml`](config/accounts.example.yml):

```yaml
lunchmoney:
  eur: 4501            # Revolut EUR account  -> Lunchmoney asset 4501
  "3771874088": 2008   # KH account number    -> Lunchmoney asset 2008
  old-card: skip       # never deliver this account
ynab:
  eur: "a1b2c3d4-...-guid"
```

## CSV banks

CSV parsing is fully **data-driven** — no per-bank code. Profiles live in
[`bankhub/data/banks.yml`](bankhub/data/banks.yml). Built-in: `kh`, `otp`,
`revolut`, `n26`, and a `generic` profile. Add a bank by adding a YAML block
(column→field mapping, delimiter, date format, row filters, dynamic-currency
detection, …) — or override any field on the CLI:

```bash
python main.py sync --source csv \
  --source-opt bank=generic --source-opt file=acme.csv \
  --source-opt columns.date=When --source-opt columns.amount="How much" \
  --dest json --dest-opt file=acme.jsonl
```

## Other file formats

OFX/QFX, QIF, MT940 and CAMT.053 just need a file — sign conventions and
account/currency detection are handled per format:

```bash
python main.py sync --source ofx   --source-opt file=stmt.qfx --dest json --dest-opt file=out.jsonl
python main.py sync --source mt940 --source-opt file=stmt.sta --dest csv  --dest-opt file=out.csv
python main.py sync --source camt  --source-opt file=stmt.xml --dest lunchmoney
```

PDF statements vary by bank, so map the columns (by header name or 0-based
index) via a profile in `bankhub/data/pdf_banks.yml` or inline options:

```bash
python main.py sync --source pdf --source-opt file=statement.pdf \
  --source-opt date_col=0 --source-opt payee_col=1 --source-opt amount_col=2 \
  --source-opt date_format=%m/%d/%Y --dest csv --dest-opt file=out.csv
```

## Aggregators

Each aggregator reads with `requests` and credentials (CLI options or env
vars). Example — SimpleFIN to Lunchmoney + YNAB at once:

```bash
export SIMPLEFIN_ACCESS_URL="https://user:pass@bridge.simplefin.org/simplefin"
python main.py sync --source simplefin \
  --dest lunchmoney --dest ynab --account-map config/accounts.yml
```

GoCardless (ex-Nordigen), TrueLayer, Yodlee, MX, Finicity, Teller and Salt
Edge follow the same shape; run `python main.py sources` and see each adapter's
docstring for its options.

## Extending: add an adapter

Sources and destinations self-register. A new destination is ~30 lines:

```python
from bankhub.destinations.base import Destination
from bankhub.models import PushResult
from bankhub.registry import register_destination

@register_destination("mybank")
class MyBankDestination(Destination):
    requires = None  # or a pip package name
    def push(self, transactions):
        results = []
        for txn in transactions:
            ...  # txn.target_account, txn.amount (signed), txn.external_id
            results.append(PushResult(txn.external_id, "created"))
        return results
```

Drop it in `bankhub/destinations/`, and it appears in `destinations` and is
usable from `sync`/`run` immediately. Sources work the same way (`fetch()`
yields `Transaction`s).

## How idempotency works

* Each transaction gets a stable `external_id` (the source's own id, or a hash
  of its fields). Ingest skips ids already in the store → **no duplicate imports**.
* Each delivery is recorded as a `(transaction, destination)` row. The engine
  only pushes transactions not yet delivered to that destination → **no
  duplicate pushes**, even across many destinations.
* Adapters that support it (Lunchmoney `external_id`, YNAB `import_id`, Actual
  `imported_id`) also carry the id downstream for a second layer of dedup.

## Testing

```bash
python run_tests.py          # runs the bankhub suite + the legacy lib suite
```

40 tests, stdlib `unittest` only — no test dependencies. CSV→CSV/JSON flows
are verified end-to-end; the live API adapters (Plaid, Flinks, Lunchmoney,
YNAB, Actual) have their pure parsers/payload-builders unit-tested against
fixtures (the network calls themselves need real credentials — see
[DECISIONS.md](DECISIONS.md)).

## Legacy

The original CSV→Lunchmoney implementation is preserved under `lib/` with its
tests in `test.py`. The three original commands (`data-import`,
`lunchmoney-id`, `data-export`) still work, now routed through the v2 engine.
See [DECISIONS.md](DECISIONS.md) for the migration notes.
