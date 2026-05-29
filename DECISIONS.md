# Decisions & Notes

Running log of decisions made while turning `banker` from a CSV→Lunchmoney
script into a universal personal-finance data hub. Written for review.

## 0. "Merge all branches"

There was nothing to merge. The remote (`latetedemelon/banker`, a fork of
`pigri/banker`) has a **single branch, `master`**, verified with
`git ls-remote --heads origin`. There is no `main` branch; the default branch
is `master`. The original repo's many historical branches (dependabot bumps,
feature PRs) were all already merged into `master` long ago. The working
branch `claude/dazzling-ptolemy-RetXt` started identical to `master`
(`0 0` ahead/behind) and now carries all the v2 work. There are no open PRs
and no other refs to consolidate.

## 1. Architecture: a pluggable hub (`bankhub/`)

**Decision.** Build a new package `bankhub/` implementing the vision —
many sources → one normalised model → many destinations — rather than
extending the original flat `lib/` scripts.

- **Normalised `Transaction`** (`models.py`) is the interlingua. Every adapter
  speaks it. Amount is a signed `Decimal`; **negative = outflow** (matches
  Lunchmoney `debit_as_negative` and most tools). Each source converts its
  native sign convention to this one.
- **Plugin registry** (`registry.py`) with `@register_source` /
  `@register_destination` decorators and lazy module discovery. Adding an
  adapter is a drop-in file; it shows up in the CLI automatically.
- **Idempotent store** (`store.py`): SQLite via peewee. One `StoredTransaction`
  per `external_id` (dedups ingest) and one `SyncRecord` per
  `(transaction, destination)` (dedups delivery). This is what makes the hub a
  hub: one ingest fans out to many destinations, and every run is safe to
  repeat.
- **Account mapping** (`mapping.py`) generalises the old `assets.yml` from
  "bank account → Lunchmoney asset" to "source account → *any* destination
  account", with `skip` / `*` / `default` semantics.
- **Engine** (`engine.py`) orchestrates ingest → map → deliver and supports
  `--dry-run` (simulates the whole flow, writes nothing).
- **Pipelines** (`config.py`): declarative YAML wiring many sources to many
  destinations, with `${ENV}` and `~` expansion so secrets stay out of files.

## 2. Removed `eval`

The original `lib/datatransform.py` built transactions with
`eval(function + "().data_transform(%s)" % (row))` — injecting each CSV row's
`repr` into `eval`. That is both a security hole and fragile (breaks on quotes,
etc.). v2 replaces it with **data-driven CSV profiles** (`data/banks.yml`):
column→field maps, row filters, dynamic-currency detection, payee fallbacks —
all as YAML, no code, no `eval`. The four original banks (kh, otp, revolut,
n26) are preserved and covered by tests producing the same normalised values.

## 3. Kept the legacy code (non-destructive)

**Decision.** Leave `lib/` and `test.py` untouched as the "legacy v1"
implementation; they still pass. `main.py` is now a thin shim over the new
CLI, and the three original commands (`data-import`, `lunchmoney-id`,
`data-export`) are preserved but routed through the v2 engine.

Rationale: non-destructive, preserves history/behaviour, lets v2 be validated
before retiring v1. **Suggested follow-up:** once v2 is trusted in production,
delete `lib/` + `test.py` and the legacy CLI commands.

**Behaviour change to note:** the store moved from `db/transaction.db` (old
schema) to `db/bankhub.db` (new schema), and account mapping now happens at
*delivery* time (via `accounts.yml`) instead of at *import* time (via
`assets.yml`). Migrate `assets.yml` → `accounts.yml` using the new
per-destination layout (see `config/accounts.example.yml`).

## 4. What's verified vs. what needs live credentials

Run offline, fully tested end-to-end:
- **CSV source** (all 4 banks + generic + inline content/overrides)
- **CSV / JSON destinations**
- **Store, engine, mapping, registry, pipeline config** (ingest, dedup,
  fan-out, idempotent re-runs, dry-run, account skip/remap)

Implemented with **pure parsers/payload-builders unit-tested against
fixtures**, but the network calls themselves need real credentials and were
**not exercised live** here:
- **Plaid** source (`/transactions/sync`; Plaid `+`=outflow → negated)
- **Flinks** source (`GetAccountsDetail`; `Credit − Debit`)
- **Lunchmoney** source + destination (insert with `external_id`)
- **YNAB** destination (milliunits, `import_id` dedup)
- **Actual** destination (via optional `actualpy`, integer cents)

These are structured so the risky parsing/formatting is tested; wiring them to
real accounts is the remaining validation step.

## 5. Smaller decisions

- **HTTP, not SDKs.** Plaid/Flinks/Lunchmoney/YNAB talk over `requests`
  directly — fewer/optional dependencies, transparent payloads. Only Actual
  needs a third-party lib (`actualpy`); it's imported lazily so listing/other
  adapters work without it installed.
- **Amount parsing heuristic.** With a comma and no dot, exactly 3 digits after
  the last comma = thousands grouping (`1,000` → 1000); otherwise a decimal
  comma (`12,50` → 12.50). European `1.234,56` is handled via an explicit
  `decimal_comma` profile flag.
- **`external_id`.** Source's own id when available (Plaid/Lunchmoney/Flinks);
  otherwise a SHA-1 of `(source, account, date, amount, payee, notes)` so the
  same statement row always dedups.
- **Testing.** stdlib `unittest` only (no pytest dependency). `run_tests.py`
  runs both suites in one process and works around the `test.py`-file vs
  `test/`-dir name clash by loading modules by path. 40 tests total.
- **CI/Docker.** The old CI used `::set-env`, which GitHub disabled in 2020
  (so it was already broken); rewritten to install deps and run `run_tests.py`.
  Dockerfile updated off the deprecated `pipenv lock --requirements`.

## 6. Ideas not yet done

- Plaid sync-cursor persistence (currently re-fetches; dedup makes it safe).
- More destinations (Actual via REST without `actualpy`, GnuCash, Firefly III,
  beancount/ledger export).
- Categorisation/rules engine between normalise and deliver.
- A small web UI or scheduled runner.

## 7. Expansion: file formats, aggregators, PDF (2nd PR)

Added a broad set of sources, all behind the same `Source` interface so they
feed any destination unchanged.

- **Bank file formats (pure, fully fixture-tested):** `ofx` (OFX 1.x SGML +
  2.x XML + QFX), `qif`, `mt940` (SWIFT, incl. structured `:86:` and reversal
  sign handling), `camt` (ISO 20022 CAMT.053, namespace-agnostic). No third-
  party deps — chosen over libraries like `ofxparse`/`mt-940` so the parsers
  are dependency-free and testable.
- **Aggregators (HTTP via `requests`; pure parsers fixture-tested, live calls
  need credentials):** `simplefin`, `gocardless` (ex-Nordigen), `truelayer`,
  `yodlee`, `mx`, `finicity`, `teller`, `saltedge`.
- **PDF (`pdf`):** incorporates the "extract tables → map columns" approach
  used by bank-PDF projects, on a `pdfplumber` backend (camelot/tabula are
  drop-in alternatives). The column-mapping + noise-row filtering is pure and
  tested; only the extraction needs the lib + a real PDF.

**Sign conventions captured per provider** (the easiest thing to get wrong):
Plaid `+`=outflow (negate); GoCardless/Finicity/Teller/Salt Edge already
signed; TrueLayer/Yodlee/MX unsigned + DEBIT/CREDIT flag; OFX/QIF signed;
MT940 D/C mark (R prefix = reversal flips); CAMT `CdtDbtInd`. Each is asserted
in tests.

60 tests total now. **Not validated against live APIs** (same caveat as §4) —
the parsers are tested against fixtures; wiring to real accounts is the
remaining step.

## 8. Direction: an "app" + a multi-language ("Node + Python") library

Per product direction, this splits into two products:

1. **The app** — the hub + CLI (and later a UI/scheduler) that *does* the
   syncing. This is the current repo.
2. **A library** others embed to connect to aggregators/formats without writing
   an adapter for each — in **Python and Node** to start.

How today's code already lines up: `bankhub` is effectively the Python library
(normalised model + `Source`/`Destination` registry + adapters), and the CLI
(`bankhub.cli` / `main.py`) is the app on top. So the Python side mostly needs
*packaging* (a `pyproject.toml`, a stable public API, publish to PyPI), not a
rewrite.

**Decisions made** (2nd round of questions):
- **Packaging:** three libraries — `core` + `files` + `connectors` — not one
  monolith and not one-per-feature (dozens of packages = too much version
  overhead).
- **Repo shape:** monorepo with a shared, language-neutral **adapter spec**
  (the normalised `Transaction` schema + provider field-maps + sign rules as
  JSON/YAML) so Python and Node stay in lock-step and a provider is described
  once.
- **Sequence:** merge the formats/aggregators work first (done, PR #2), then
  **package Python first** before any Node work.

## 9. Python packaging (this PR)

First concrete step of §8's "package Python first". Done **in place** (the
physical move into `packages/python/` is a separate, mechanical follow-up so
this PR stays reviewable):

- **`pyproject.toml`** (setuptools): runtime deps `click`/`peewee`/`pyyaml`;
  optional extras `connectors`/`http` (requests), `pdf` (pdfplumber),
  `actual` (actualpy), `all`, `dev`. Console script `bankhub = bankhub.cli:main`.
  Ships `bankhub/data/*.yml` via `package-data` + `MANIFEST.in`.
- **Curated public API:** `bankhub/__init__.py` now re-exports the full stable
  surface (model, `Source`/`Destination`, registry, `Engine`/`Store`,
  `AccountMap`, pipeline config, errors) — 35 names in `__all__`. Bumped to
  **0.3.0**.
- **Verified:** built wheel + sdist, installed the wheel in a clean venv, and
  confirmed the CLI runs from outside the source tree, the packaged YAML
  profiles load, CSV parsing + engine run, and the `[all]` extra pulls
  requests/pdfplumber. 60 tests still green.

**Open item — licensing.** There is no `LICENSE` file and this repo is a fork
of `pigri/banker` (orig. author David Papp). I did **not** fabricate one. I
removed the MIT assertion from `pyproject.toml` and left a NOTE there: confirm
the intended license and add a `LICENSE` file before publishing to PyPI.

**Next:** carve `bankhub` into `core`/`files`/`connectors` and lay out the
monorepo (`packages/python/*`, `spec/`), then port `core` + a few reference
adapters to Node to validate the shared spec.
