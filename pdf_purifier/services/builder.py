"""Schritt 3: Wandelt das bereinigte Markdown via Pandoc zurück in eine PDF."""

from __future__ import annotations

import subprocess
from pathlib import Path


class BuilderError(RuntimeError):
    """Wird ausgelöst, wenn Pandoc die PDF nicht erzeugen kann."""


def _document_title(markdown_path: Path) -> str:
    """Erste Überschrift des Dokuments als PDF-Titel.

    Ein *leerer* Titel hilft nicht: Pandoc fällt dann auf den Dateinamen der
    Zwischendatei zurück, und "temp_cleaned" landet als /Title im fertigen PDF.
    """
    try:
        for line in markdown_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("#") and stripped.strip("# ").strip():
                return stripped.lstrip("#").strip()
    except OSError:
        pass
    return " "  # nie leer - sonst greift wieder der Dateiname


def convert_markdown_to_pdf(
    input_md: str | Path,
    output_pdf_path: str | Path,
    pdf_engine: str = "weasyprint",
) -> None:
    """Ruft Pandoc mit der konfigurierten PDF-Engine auf."""
    print("[3/4] Generiere neue PDF mit Pandoc...")

    input_md = Path(input_md)
    # Docling verweist auf die Bilder als Dateien im Nachbarordner `<name>_artifacts/`.
    # Beide Verzeichnisse in den Suchpfad, damit die Auflösung unabhängig vom
    # Arbeitsverzeichnis funktioniert.
    resource_path = f"{input_md.parent}:{input_md.parent.parent}"

    command = [
        "pandoc",
        str(input_md),
        "-o",
        str(output_pdf_path),
        f"--pdf-engine={pdf_engine}",
        f"--resource-path={resource_path}",
        # pagetitle statt title: setzt /Title im PDF, wird aber - anders als
        # `title` - NICHT als Überschrift in den Dokumentkörper gedruckt.
        "-V",
        f"pagetitle={_document_title(input_md)}",
        "--standalone",
    ]

    try:
        subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except FileNotFoundError as exc:
        raise BuilderError(
            f"\n[Fehler] Pandoc oder {pdf_engine} ist nicht auf deinem System installiert/im PATH.\n"
            "Bitte installiere beide Tools nach. Das saubere Markdown existiert jedoch bereits."
        ) from exc
    except subprocess.CalledProcessError as exc:
        raise BuilderError(
            f"\n[Fehler] Pandoc-Fehler: {exc.stderr.decode('utf-8')}"
        ) from exc

    print(f"-> Neue PDF erfolgreich unter '{output_pdf_path}' erstellt!")
