# spec/ — the shared adapter spec

The **language-neutral** definition every banker runtime consumes, so a provider
is described once and behaves identically everywhere (Python today, Node next).

| File | What |
| --- | --- |
| [`SPEC.md`](./SPEC.md) | the normative contract: model, source/destination behaviour, the de-dup algorithm, discovery, options, errors |
| [`schemas/transaction.schema.json`](./schemas/transaction.schema.json) | JSON Schema for the normalised `Transaction` (signed amount, decimal-as-string, ISO dates) |
| [`schemas/push-result.schema.json`](./schemas/push-result.schema.json) | per-transaction delivery outcome |
| [`schemas/account.schema.json`](./schemas/account.schema.json) | a logical account a source can enumerate |
| [`adapters.md`](./adapters.md) | canonical adapter-name registry (20 sources / 12 destinations) shared across runtimes |

## Source of truth & conformance

The Python package under [`../packages/python/`](../packages/python/) is the
**reference implementation**. The schemas are kept honest by
`packages/python/tests/test_spec.py`, which validates real model objects against
them and checks the `external_id` conformance vector — so the model and this
spec can't silently drift. Any port must reproduce that vector exactly (see
[`SPEC.md` §2](./SPEC.md#2-identity--de-duplication)).

## Still planned

- **`providers/*.{json,yml}`** — per-provider field-maps / sign rules, seeded
  from the Python package's `data/banks.yml` and `data/pdf_banks.yml`.
- **`account-map.schema.json`** — schema for the account-mapping config.
- A tiny **Node** package consuming these schemas — the first port milestone.
