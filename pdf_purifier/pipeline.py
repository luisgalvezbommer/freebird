"""Orchestriert die vier Schritte der PDF-Bereinigung."""

from __future__ import annotations

from pdf_purifier.config import Settings
from pdf_purifier.services.builder import convert_markdown_to_pdf
from pdf_purifier.services.cleanup import clean_temporary_files
from pdf_purifier.services.extractor import convert_pdf_to_markdown
from pdf_purifier.services.preflight import check_system_dependencies
from pdf_purifier.services.rewriter import process_markdown_with_ai


def run_pipeline(settings: Settings, *, keep_temp: bool = False) -> None:
    """Führt den kompletten Ablauf aus: Prüfen -> Extrahieren -> Umschreiben -> PDF."""
    # Erst prüfen, ob alles da ist!
    check_system_dependencies(settings.pdf_engine)

    # Danach die Pipeline starten
    artifacts_dir = convert_pdf_to_markdown(settings.input_pdf, settings.temp_md)
    process_markdown_with_ai(settings.temp_md, settings.temp_clean_md, settings)
    convert_markdown_to_pdf(settings.temp_clean_md, settings.output_pdf, settings.pdf_engine)

    if keep_temp:
        print("[4/4] Behalte temporäre Zwischendateien (--keep-temp).")
    else:
        clean_temporary_files([settings.temp_md, settings.temp_clean_md, artifacts_dir])
