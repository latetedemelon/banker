# bankhub-files

File-format adapters for [bankhub](https://github.com/latetedemelon/banker).

- **Sources:** CSV (per-bank profiles), OFX / QFX, QIF, MT940, CAMT.053, PDF, Excel (.xlsx).
- **Destinations:** CSV, JSON, Excel (.xlsx), OFX/QFX (Quicken/Simplifi/GnuCash
  import), Copilot CSV, Tiller CSV, GnuCash (native, via `piecash`).

```bash
pip install bankhub-files             # registers automatically with bankhub-core
pip install "bankhub-files[pdf]"      # + the PDF statement source (pdfplumber)
pip install "bankhub-files[xlsx]"     # + the Excel source/destination (openpyxl)
pip install "bankhub-files[gnucash]"  # + the native GnuCash destination (piecash)
```

Installing this package makes its adapters available through the core API — no
imports from `bankhub_files` needed:

```python
import bankhub

bankhub.build_source("ofx", file="x.qfx")
bankhub.build_source("csv", bank="revolut", file="revolut.csv")
bankhub.build_destination("json", file="out.jsonl")
```
