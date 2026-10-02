"""Schritt 1: Konvertiert das PDF mittels IBM Docling in sauberes Markdown."""

from __future__ import annotations

from pathlib import Path

from pdf_purifier.services.repair import repair_placeholders


class ExtractionError(RuntimeError):
    """Wird ausgelöst, wenn Docling das PDF nicht konvertieren kann."""


def convert_pdf_to_markdown(
    pdf_path: str | Path,
    output_md_path: str | Path,
) -> Path | None:
    """Extrahiert Text **und Bilder** aus ``pdf_path`` und schreibt Markdown.

    Gibt das Verzeichnis mit den extrahierten Bildern zurück (oder ``None``),
    damit die Pipeline es später wieder aufräumen kann.
    """
    print("[1/4] Extrahiere Layout, Text und Bilder aus PDF via Docling...")

    # Lazy import: Docling ist schwer und wird nur für diesen Schritt benötigt.
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption
    from docling_core.types.doc import ImageRefMode

    output_md_path = Path(output_md_path)
    # Bilder landen in einem Geschwisterordner. Absoluter Pfad, damit Pandoc und
    # WeasyPrint sie unabhängig vom Arbeitsverzeichnis finden.
    artifacts_dir = output_md_path.with_name(f"{output_md_path.stem}_artifacts").resolve()

    try:
        pipeline_options = PdfPipelineOptions()
        # Ohne diese Option schreibt Docling nur "<!-- image -->" statt der Bilder.
        pipeline_options.generate_picture_images = True
        pipeline_options.images_scale = 2.0  # doppelte Auflösung für den Druck

        converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
            }
        )
        result = converter.convert(str(pdf_path))
        result.document.save_as_markdown(
            output_md_path,
            artifacts_dir=artifacts_dir,
            # Default ist PLACEHOLDER - dabei gehen alle Bilder verloren.
            image_mode=ImageRefMode.REFERENCED,
        )
    except Exception as exc:  # noqa: BLE001 - Original: klare Meldung + Abbruch
        raise ExtractionError(f"CRITICAL ERROR in Schritt 1: {exc}") from exc

    # Ligaturen/Emoji ohne ToUnicode-Eintrag reparieren, solange der Text noch
    # sauber getrennt vorliegt - also VOR der KI.
    repaired, report = repair_placeholders(output_md_path.read_text(encoding="utf-8"))
    output_md_path.write_text(repaired, encoding="utf-8")
    report.print_summary()

    print(f"-> PDF erfolgreich in '{output_md_path}' konvertiert.")
    if artifacts_dir.is_dir() and any(artifacts_dir.iterdir()):
        return artifacts_dir
    return None
