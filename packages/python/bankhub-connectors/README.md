# bankhub-connectors

API / aggregator adapters for [bankhub](https://github.com/latetedemelon/banker).

- **Sources:** Plaid, SimpleFIN, Yodlee, GoCardless, TrueLayer, MX, Finicity,
  Teller, Salt Edge, Flinks, Lunchmoney.
- **Destinations:** Lunchmoney, YNAB, Actual Budget.

```bash
pip install bankhub-connectors            # registers automatically with bankhub-core
pip install "bankhub-connectors[actual]"  # + the Actual Budget SDK (actualpy)
```

These adapters speak over HTTP (so the package depends on `requests`); heavy
SDKs are imported lazily, so listing and introspection work even before you've
configured credentials.

```python
import bankhub

bankhub.build_source("simplefin")          # reads $SIMPLEFIN_ACCESS_URL
bankhub.build_destination("ynab", token="…", budget="…", account="…")
```
