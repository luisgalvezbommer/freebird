# PDF Purifier

Wasserzeichen aus gekauften PDFs entfernen: **Docling** (PDF → Markdown) → **DeepSeek** (umformulieren) → **Pandoc** (Markdown → PDF).

## Installation

```bash
python -m venv .venv && source .venv/bin/activate

# PyTorch ZUERST als CPU-Version – sonst lädt pip den ~3 GB großen CUDA-Stack:
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu

pip install -e .

sudo apt install pandoc weasyprint
```

## Konfiguration

```bash
cp .env.example .env
```

In `.env` anpassen:

```dotenv
DEEPSEEK_API_KEY=sk-dein-api-key
INPUT_PDF=kauf_datei.pdf
OUTPUT_PDF=sauberes_buch.pdf
PDF_ENGINE=weasyprint
```

## Verwendung

```bash
python main.py
```

Das Ergebnis landet unter `OUTPUT_PDF`.

## Hinweise

- `PDF_ENGINE=weasyprint` nutzen – `wkhtmltopdf` gibt es in Ubuntu nicht mehr.
- Beim ersten Lauf lädt Docling Modelle von Hugging Face nach (einige hundert MB).
- Nur für den privaten Gebrauch. Geschützte Werke weiterzuverbreiten ist rechtswidrig.
