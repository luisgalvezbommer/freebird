"""pdf_purifier - KI-gestützte PDF-Bereinigung.

Pipeline: PDF -> Markdown (Docling) -> Umschreibung (DeepSeek) -> PDF (Pandoc).

Das Package kapselt jeden Verarbeitungsschritt in einem eigenen Modul unter
``pdf_purifier.services``; die Orchestrierung liegt in ``pdf_purifier.pipeline``.
"""

__version__ = "0.1.0"

__all__ = ["__version__"]
