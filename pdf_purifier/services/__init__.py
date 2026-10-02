"""Einzelne Verarbeitungsschritte der PDF-Bereinigung.

Jedes Modul kapselt genau einen Schritt:

* :mod:`pdf_purifier.services.preflight` - System-Abhängigkeiten prüfen
* :mod:`pdf_purifier.services.extractor` - PDF -> Markdown (Docling)
* :mod:`pdf_purifier.services.rewriter`  - Umschreiben (DeepSeek API)
* :mod:`pdf_purifier.services.builder`   - Markdown -> PDF (Pandoc)
* :mod:`pdf_purifier.services.cleanup`   - Temporäre Dateien löschen
"""

from __future__ import annotations

__all__ = ["preflight", "extractor", "rewriter", "builder", "cleanup"]
