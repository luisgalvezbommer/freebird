"""Schritt 1: Konvertiert das PDF mittels IBM Docling in sauberes Markdown."""

from __future__ import annotations

from pathlib import Path

from pdf_purifier.services.images import sanitize_images
from pdf_purifier.services.repair import repair_placeholders


class ExtractionError(RuntimeError):
    """Wird ausgelöst, wenn Docling das PDF nicht konvertieren kann."""


#: Ab so vielen Zeichen pro Seite gilt ein PDF als "hat einen Textlayer".
_TEXT_LAYER_MIN_CHARS = 80


def has_text_layer(pdf_path: str | Path) -> bool:
    """Prüft, ob das PDF einen echten Textlayer hat.

    OCR ist dann reine Verschwendung: auf einem Vektor-PDF findet sie nichts
    ("text detection result is empty"), kostet aber das Laden von drei
    neuronalen Netzen - gemessen rund 47 der 53 Sekunden Laufzeit.
    """
    try:
        import pypdfium2 as pdfium

        document = pdfium.PdfDocument(str(pdf_path))
        pages = min(len(document), 3)
        if pages == 0:
            return False
        characters = sum(
            len(document[index].get_textpage().get_text_range()) for index in range(pages)
        )
        return characters / pages >= _TEXT_LAYER_MIN_CHARS
    except Exception:  # noqa: BLE001 - im Zweifel lieber OCR nutzen
        return False


def _use_ocr(pdf_path: str | Path, setting: str) -> bool:
    """Entscheidet anhand von ``OCR=auto|on|off``, ob OCR laufen soll."""
    if setting == "on":
        return True
    if setting == "off":
        return False
    return not has_text_layer(pdf_path)


def _bbox_width_mm(picture: object) -> float | None:
    """Breite des Bildes im Original-PDF, in Millimetern."""
    try:
        bbox = picture.prov[0].bbox  # type: ignore[attr-defined]
        width_pt = getattr(bbox, "width", None)
        if width_pt is None:
            width_pt = abs(bbox.r - bbox.l)
        return round(float(width_pt) / 72 * 25.4, 1)
    except Exception:  # noqa: BLE001 - ohne Größe wird eben nicht skaliert
        return None


def _annotate_image_sizes(document: object, markdown: str) -> tuple[str, int]:
    """Hängt jedem Bild seine Originalbreite an (``{width=63.5mm}``).

    Docling schreibt nur den Dateinamen. Ohne Größenangabe platziert WeasyPrint
    das Bild nach seiner Pixelzahl - dabei schrumpfte das Foto von 500x750 auf
    136x128 Pixel. Die Bounding-Box aus dem Original stellt die ursprüngliche
    Darstellungsgröße wieder her.

    Gibt den neuen Markdown-Text und die Anzahl der ergänzten Größen zurück.
    """
    try:
        pictures = list(document.pictures)  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        return markdown, 0
    if not pictures:
        return markdown, 0

    annotated: list[str] = []
    index = 0
    count = 0
    for line in markdown.split("\n"):
        if index < len(pictures) and line.lstrip().startswith("![") and "{" not in line:
            width_mm = _bbox_width_mm(pictures[index])
            index += 1
            if width_mm:
                line = f"{line.rstrip()}{{width={width_mm}mm}}"
                count += 1
        annotated.append(line)
    return "\n".join(annotated), count


def convert_pdf_to_markdown(
    pdf_path: str | Path,
    output_md_path: str | Path,
    *,
    ocr: str = "auto",
    images_scale: float = 1.0,
    image_sanitize: str = "metadata",
    max_workers: int = 4,
    page_range: tuple[int, int] | None = None,
) -> Path | None:
    """Extrahiert Text **und Bilder** aus ``pdf_path`` und schreibt Markdown.

    Gibt das Verzeichnis mit den extrahierten Bildern zurück (oder ``None``),
    damit die Pipeline es später wieder aufräumen kann.
    """
    use_ocr = _use_ocr(pdf_path, ocr)
    print("[1/4] Extrahiere Layout, Text und Bilder aus PDF via Docling...")
    print(
        f"      OCR {'an' if use_ocr else 'aus'} (OCR={ocr}), "
        f"Bildauflösung x{images_scale:g}"
        + (f", Seiten {page_range[0]}-{page_range[1]}" if page_range else "")
    )

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
        pipeline_options.images_scale = images_scale
        # OCR nur, wenn wirklich nötig - sonst kostet sie ~47 s für nichts.
        pipeline_options.do_ocr = use_ocr

        converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
            }
        )
        # Nur einen Seitenblock lesen, wenn einer angegeben wurde.
        convert_options: dict[str, object] = {}
        if page_range is not None:
            convert_options["page_range"] = page_range
        result = converter.convert(str(pdf_path), **convert_options)
        result.document.save_as_markdown(
            output_md_path,
            artifacts_dir=artifacts_dir,
            # Default ist PLACEHOLDER - dabei gehen alle Bilder verloren.
            image_mode=ImageRefMode.REFERENCED,
        )
    except Exception as exc:  # noqa: BLE001 - Original: klare Meldung + Abbruch
        raise ExtractionError(f"CRITICAL ERROR in Schritt 1: {exc}") from exc

    markdown = output_md_path.read_text(encoding="utf-8")

    # Bilder bereinigen (Metadaten weg, optional neu kodieren) - parallel.
    renames = sanitize_images(artifacts_dir, mode=image_sanitize, workers=max_workers)
    for old_name, new_name in renames.items():
        markdown = markdown.replace(old_name, new_name)

    # Bildgrößen aus dem Original übernehmen - sonst platziert WeasyPrint sie
    # nach Pixelzahl und das Foto schrumpft.
    markdown, sized = _annotate_image_sizes(result.document, markdown)
    if sized:
        print(f"-> {sized} Bild(er) auf Originalgröße gesetzt.")

    # Ligaturen/Emoji ohne ToUnicode-Eintrag reparieren, solange der Text noch
    # sauber getrennt vorliegt - also VOR der KI.
    repaired, report = repair_placeholders(markdown)
    output_md_path.write_text(repaired, encoding="utf-8")
    report.print_summary()

    print(f"-> PDF erfolgreich in '{output_md_path}' konvertiert.")
    if artifacts_dir.is_dir() and any(artifacts_dir.iterdir()):
        return artifacts_dir
    return None
