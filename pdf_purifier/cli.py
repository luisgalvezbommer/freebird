"""Kommandozeilen-Einstiegspunkt.

Aufrufbeispiele::

    python main.py
    python -m pdf_purifier
    pdf-purifier --input kauf_datei.pdf --output sauberes_buch.pdf
"""

from __future__ import annotations

import argparse
from pathlib import Path

from pdf_purifier.config import Settings
from pdf_purifier.pipeline import run_pipeline
from pdf_purifier.services.builder import BuilderError
from pdf_purifier.services.extractor import ExtractionError
from pdf_purifier.services.rewriter import RewritingError

# Erwartbare Laufzeitfehler -> saubere Meldung statt Traceback.
_KNOWN_ERRORS = (ExtractionError, RewritingError, BuilderError)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pdf-purifier",
        description="Entfernt Wasserzeichen aus PDFs: Docling -> DeepSeek -> Pandoc.",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=None,
        help="Pfad zur .env-Datei (Standard: <projekt>/.env)",
    )
    parser.add_argument(
        "--input",
        dest="input_pdf",
        type=Path,
        default=None,
        help="Eingabe-PDF (überschreibt INPUT_PDF)",
    )
    parser.add_argument(
        "--output",
        dest="output_pdf",
        type=Path,
        default=None,
        help="Ausgabe-PDF (überschreibt OUTPUT_PDF)",
    )
    parser.add_argument(
        "--engine",
        dest="pdf_engine",
        default=None,
        help="Pandoc-PDF-Engine (Standard: weasyprint)",
    )
    parser.add_argument(
        "--keep-temp",
        action="store_true",
        help="Temporäre Markdown-Dateien nicht löschen",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Gespeicherte DeepSeek-Antworten ignorieren und neu anfragen",
    )
    return parser


def _apply_overrides(settings: Settings, args: argparse.Namespace) -> Settings:
    changes: dict[str, object] = {}
    if args.input_pdf is not None:
        changes["input_pdf"] = args.input_pdf
    if args.output_pdf is not None:
        changes["output_pdf"] = args.output_pdf
    if args.pdf_engine is not None:
        changes["pdf_engine"] = args.pdf_engine
    return settings.with_overrides(**changes) if changes else settings


def main(argv: list[str] | None = None) -> int:
    """Einstiegspunkt; gibt den Exit-Code zurück."""
    args = build_parser().parse_args(argv)

    try:
        settings = Settings.from_env(args.env_file)
    except ValueError as exc:
        print(f"[Fehler] Ungültige Konfiguration: {exc}")
        return 2

    if not settings.has_api_key:
        print(
            "[Warnung] Kein gültiger DEEPSEEK_API_KEY in der .env gefunden. "
            "Die KI-Umschreibung schlägt fehl und der Originaltext wird verwendet."
        )

    settings = _apply_overrides(settings, args)

    try:
        run_pipeline(settings, keep_temp=args.keep_temp, use_cache=not args.no_cache)
    except _KNOWN_ERRORS as exc:
        print(str(exc))
        return 1
    return 0
