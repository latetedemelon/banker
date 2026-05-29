# bankhub-files

File-format adapters for [bankhub](https://github.com/latetedemelon/banker).

- **Sources:** CSV (per-bank profiles), OFX / QFX, QIF, MT940, CAMT.053, PDF.
- **Destinations:** CSV, JSON.

```bash
pip install bankhub-files          # registers automatically with bankhub-core
pip install "bankhub-files[pdf]"   # + the PDF statement source (pdfplumber)
```

Installing this package makes its adapters available through the core API — no
imports from `bankhub_files` needed:

```python
import bankhub

bankhub.build_source("ofx", file="x.qfx")
bankhub.build_source("csv", bank="revolut", file="revolut.csv")
bankhub.build_destination("json", file="out.jsonl")
```
