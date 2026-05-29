# spec/ — the shared adapter spec *(planned)*

This directory will hold the **language-neutral** definition that every banker
runtime (Python today, Node next) consumes, so a provider is described once
and behaves identically everywhere:

- **`transaction.schema.json`** — JSON Schema for the normalised
  `Transaction` model (field names, types, the signed-amount convention where
  *negative = money out*).
- **`providers/*.{json,yml}`** — per-provider field-maps and sign rules. The
  Python package's `bankhub/data/banks.yml` and `pdf_banks.yml` are the seed
  for these.
- **`account-map.schema.json`** — schema for the account-mapping config.

Until this lands, the Python package under
[`../packages/python/`](../packages/python/) is the source of truth for the
model and provider profiles. Extracting the spec (and pointing Python at it)
is the bridge to the Node port — see [`../DECISIONS.md`](../DECISIONS.md).
