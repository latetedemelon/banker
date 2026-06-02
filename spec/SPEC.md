# bankhub adapter spec — v0

The **language-neutral contract** every bankhub runtime implements. Python is
the reference implementation today; the Node port consumes this same spec so a
provider behaves identically in both. This document is normative; the JSON
Schemas under [`schemas/`](./schemas) are the machine-readable companion.

> **Status:** v0, tracking `bankhub` 0.4.x. Until v1 the shapes may still shift;
> changes are recorded in [`../DECISIONS.md`](../DECISIONS.md).

## 1. The model

Three types, defined by JSON Schema and shared by every adapter:

| Type | Schema | Role |
| --- | --- | --- |
| **Transaction** | [`transaction.schema.json`](./schemas/transaction.schema.json) | the interlingua — sources emit it, destinations consume it |
| **PushResult** | [`push-result.schema.json`](./schemas/push-result.schema.json) | per-transaction delivery outcome |
| **Account** | [`account.schema.json`](./schemas/account.schema.json) | a logical account a source can enumerate |

Two rules make the JSON portable and exact across languages:

- **Money is a decimal string, never a float.** `amount` and `balance` are
  serialised as strings (e.g. `"-12.34"`) so no binary-float rounding creeps in.
  Implementations must use a real decimal type internally.
- **`amount` is signed: negative = money out (debit/outflow), positive = money
  in (inflow).** Each *source* is responsible for normalising its provider's
  native sign convention to this one. Dates are ISO-8601 (`YYYY-MM-DD`).

(The Python dataclass also carries a transient `dest_account` and a `raw`
original-record dict; `dest_account` is never serialised — see §5.)

## 2. Identity & de-duplication

Every `Transaction` carries an `external_id` that is **stable across runs** for
the same logical transaction. The engine stores it (unique-indexed) and skips
anything it has already seen, so re-importing a statement never double-counts.

- If the provider exposes its own immutable id (Plaid `transaction_id`,
  Lunchmoney `id`, Stripe `id`, OFX `FITID`, …), **use it**.
- Otherwise **derive one deterministically** with the canonical algorithm
  below. Both runtimes MUST produce byte-identical ids so a transaction
  ingested by Python and re-seen by Node (or vice-versa) de-duplicates.

```
external_id = sha1_hex(
    join("|", [ source, account_id, date_iso, amount_str,
                clean_text(payee), clean_text(notes), extra ])
)
```

where `date_iso` is `YYYY-MM-DD`, `amount_str` is the decimal's canonical string
(e.g. `"-12.34"`), `extra` is an optional disambiguator (default `""`), and
`clean_text` is defined in §8. The join string is UTF-8 encoded; the result is
the 40-char lowercase SHA-1 hex digest.

**Conformance vector** (implementations must reproduce this exactly):

```
source      = "csv:revolut"
account_id  = "eur"
date        = "2024-01-15"
amount      = "-12.34"
payee       = "Coffee"
notes       = ""
extra       = ""
joined      = "csv:revolut|eur|2024-01-15|-12.34|Coffee||"
external_id = "cc5d73ab8c0c76615f8b177fa656a156e6b0d958"
```

> Because `amount_str` is the decimal's string form, an adapter must construct
> amounts consistently (`"5"` and `"5.00"` hash differently). When in doubt,
> normalise before hashing.

## 3. Source contract

A **source** pulls native records from somewhere and yields `Transaction`s.

| Member | Contract |
| --- | --- |
| `name` | unique registered id, e.g. `"csv"`, `"plaid"` (see [`adapters.md`](./adapters.md)) |
| `requires` | optional third-party package this adapter needs at fetch time, or null |
| `source_id` | the value stamped on `Transaction.source`; defaults to `name`, overridden when the adapter namespaces output (e.g. `"csv:revolut"`) |
| construction | receives string-keyed **options** (see §7); must stay cheap — no network/SDK work |
| `fetch()` | returns/yields `Transaction`s; this is where I/O and lazy dependency imports happen |
| `list_accounts()` | optional; returns `Account`s |

Rules: keep construction side-effect-free so listing/introspection works
without credentials or optional deps installed; import heavy SDKs **lazily**
inside `fetch()`; normalise the sign convention (§1) and set a stable
`external_id` (§2).

## 4. Destination contract

A **destination** delivers `Transaction`s to a target system.

| Member | Contract |
| --- | --- |
| `name` | unique registered id, e.g. `"ynab"`, `"ofx"` |
| `requires` | optional third-party package, or null |
| construction | string-keyed **options** (§7) |
| `push(transactions)` | returns **exactly one `PushResult` per input transaction, in the same order** |

Rules: be **idempotent where possible** — carry `external_id` through to the
remote system (YNAB `import_id`, Firefly `external_id`, OFX `FITID`) so re-runs
are caught remotely too, on top of the local store. Report duplicates as
`status:"skipped"`, failures as `status:"error"` with a message (don't throw for
a single bad row). Append-only file destinations are naturally idempotent
because the engine only ever hands over not-yet-delivered rows.

## 5. Account mapping

A transaction's source account is mapped to a destination account by the engine
just before `push`, into the transient `dest_account`. Destinations read the
**`target_account`** = `dest_account || account_id`. `dest_account` is never
persisted.

## 6. Discovery & naming

Adapters self-register under a unique `name`. A runtime discovers installed
adapter packages via a manifest mechanism — in Python the `bankhub.plugins`
entry-point group, each entry importing a package whose registration
decorators run. The **canonical names and their owning package** are the
cross-runtime contract and are listed in [`adapters.md`](./adapters.md); a Node
adapter for `"csv"` must accept the same name and comparable options.

## 7. Options conventions

- Options are **string-keyed** and string-valued at the boundary (they arrive
  from CLI `--source-opt key=value` / `--dest-opt key=value` or a YAML block);
  adapters coerce as needed.
- Secrets fall back to **environment variables** (e.g. `PLAID_CLIENT_ID`,
  `YNAB_TOKEN`), documented per adapter.
- Common file-source options: `file`, `bank`, `date_format`, `decimal_comma`,
  `currency`, `account`.

## 8. Canonical normalisation helpers

For parity, both runtimes implement these identically:

- **`clean_text(s)`** — `null` → `""`; otherwise collapse every run of
  whitespace (`\s+`) to a single space and trim. Example:
  `"  Coffee   Shop "` → `"Coffee Shop"`.
- **`parse_amount`** — tolerant decimal parser: strips currency symbols and
  thousands separators, understands parenthesised negatives `(12.34)` and
  European `1.234,56` (when `decimal_comma`), returns a decimal.
- **`parse_date`** — ISO-8601 first, then a fixed list of common fallbacks, or
  an explicit `strptime`-style format when given.

## 9. Error taxonomy

| Condition | Signal |
| --- | --- |
| Misconfiguration (missing option/credential) | `ConfigError` |
| Optional dependency not installed | `MissingDependencyError(adapter, package)` |
| Source fetch/parse failure | `SourceError` |
| Unknown adapter name | `PluginError` |
| Single-row delivery failure | `PushResult{status:"error", error:"..."}` (not an exception) |
