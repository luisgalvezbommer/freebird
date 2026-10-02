"""Orchestriert den Ablauf: Prüfen -> Extrahieren -> Umschreiben -> PDF.

Große PDFs werden in Seitenblöcke ("Parts") zerlegt. Jeder Block läuft einzeln
durch Extraktion und Umschreibung; am Ende werden die Ergebnisse zu *einem*
Dokument zusammengesetzt. Warum das so gemacht wird:

* **Speicher** - Docling hält das komplette Dokument im RAM. Bei 1400 Seiten
  sind das schnell mehrere GB. Ein Block von z. B. 150 Seiten begrenzt den
  Bedarf auf diesen Ausschnitt.
* **Fortsetzen** - Ein fertiger Block wird als Datei abgelegt. Bricht der Lauf
  nach 6 von 10 Blöcken ab, werden beim nächsten Start genau diese 6
  übersprungen.
* **Kosten** - Zusammen mit dem Antwort-Cache wird kein Text zweimal bezahlt.

Die Blöcke werden *nicht* als einzelne PDFs zusammengefügt: jedes Block-Markdown
verweist über absolute Pfade auf seine eigenen Bilder, deshalb genügt am Ende
ein einziger Pandoc-/WeasyPrint-Lauf über das zusammengesetzte Markdown. Damit
braucht es kein zusätzliches PDF-Werkzeug.
"""

from __future__ import annotations

import gc
import time
from pathlib import Path

from pdf_purifier.config import Settings
from pdf_purifier.services.builder import convert_markdown_to_pdf
from pdf_purifier.services.cleanup import clean_temporary_files
from pdf_purifier.services.extractor import convert_pdf_to_markdown
from pdf_purifier.services.preflight import check_system_dependencies
from pdf_purifier.services.rewriter import process_markdown_with_ai

#: Erzwingt im zusammengesetzten Dokument einen Seitenumbruch zwischen Blöcken.
_PAGE_BREAK = '<div style="break-after: page"></div>'


def _format_duration(seconds: float) -> str:
    """Formatiert eine Dauer als ``H h M min S s`` (nur die nötigen Teile)."""
    total = round(seconds)
    minutes, rest = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours} h {minutes} min {rest} s"
    if minutes:
        return f"{minutes} min {rest} s"
    return f"{rest} s"


def count_pages(pdf_path: str | Path) -> int:
    """Seitenzahl des PDFs (0, wenn sie nicht lesbar ist)."""
    try:
        import pypdfium2 as pdfium

        return len(pdfium.PdfDocument(str(pdf_path)))
    except Exception:  # noqa: BLE001 - ohne Seitenzahl läuft alles am Stück
        return 0


def _parts_dir(settings: Settings) -> Path:
    """Arbeitsordner der Blöcke. Sein Inhalt ist zugleich der Fortschritt."""
    return settings.project_root / ".pdf_purifier_parts" / Path(settings.input_pdf).stem


def _part_markdown(parts_dir: Path, index: int) -> Path:
    return parts_dir / f"part_{index:04d}_clean.md"


def _run_part(
    settings: Settings,
    start: int,
    end: int,
    parts_dir: Path,
    index: int,
    *,
    use_cache: bool,
) -> Path:
    """Extrahiert und schreibt einen Seitenblock; gibt die Markdown-Datei zurück."""
    raw_md = parts_dir / f"part_{index:04d}.md"
    clean_md = _part_markdown(parts_dir, index)

    artifacts_dir = convert_pdf_to_markdown(
        settings.input_pdf,
        raw_md,
        page_range=(start, end),
        ocr=settings.ocr,
        images_scale=settings.images_scale,
        image_sanitize=settings.image_sanitize,
        max_workers=settings.max_workers,
    )
    process_markdown_with_ai(raw_md, clean_md, settings, use_cache=use_cache)

    # Rohfassung sofort weg - die Bilder bleiben für die Endmontage liegen.
    raw_md.unlink(missing_ok=True)
    del artifacts_dir
    # Speicher des Blocks freigeben, bevor der nächste startet.
    gc.collect()
    return clean_md


def _assemble(part_files: list[Path], target: Path) -> None:
    """Setzt die Blöcke in Reihenfolge zu einem Markdown-Dokument zusammen."""
    with target.open("w", encoding="utf-8") as handle:
        for path in part_files:
            handle.write(path.read_text(encoding="utf-8"))
            handle.write(f"\n\n{_PAGE_BREAK}\n\n")


def _run_batched(
    settings: Settings,
    total_pages: int,
    block: int,
    *,
    use_cache: bool,
) -> list[object]:
    """Verarbeitet das PDF blockweise und setzt die Teile zusammen.

    Gibt die Pfade zurück, die am Ende aufgeräumt werden sollen.
    """
    parts_dir = _parts_dir(settings)
    parts_dir.mkdir(parents=True, exist_ok=True)

    ranges = [
        (index, start, min(start + block - 1, total_pages))
        for index, start in enumerate(range(1, total_pages + 1, block), start=1)
    ]
    print(
        f"-> {total_pages} Seiten -> {len(ranges)} Blöcke à {block} Seiten. "
        f"Arbeitsordner: {parts_dir}"
    )
    print("   (Fertige Blöcke werden beim nächsten Lauf übersprungen.)")

    part_files: list[Path] = []
    for index, start, end in ranges:
        clean_md = _part_markdown(parts_dir, index)
        if clean_md.exists() and clean_md.stat().st_size > 0:
            print(f"   Block {index}/{len(ranges)} (S. {start}-{end}): schon fertig, übersprungen.")
            part_files.append(clean_md)
            continue
        print(f"\n   --- Block {index}/{len(ranges)} (Seiten {start}-{end}) ---")
        part_files.append(_run_part(settings, start, end, parts_dir, index, use_cache=use_cache))

    _assemble(part_files, settings.temp_clean_md)
    print(f"\n-> {len(part_files)} Blöcke zu einem Dokument zusammengesetzt.")

    cleanup: list[object] = [parts_dir]
    cleanup.extend(parts_dir.glob("*_artifacts"))
    return cleanup


def run_pipeline(
    settings: Settings,
    *,
    keep_temp: bool = False,
    use_cache: bool = True,
) -> None:
    """Führt den kompletten Ablauf aus: Prüfen -> Extrahieren -> Umschreiben -> PDF."""
    started = time.perf_counter()

    # Erst prüfen, ob alles da ist!
    check_system_dependencies(settings.pdf_engine)

    pages = count_pages(settings.input_pdf)
    block = settings.pages_per_part
    temporary: list[object] = [settings.temp_md, settings.temp_clean_md]

    if block and pages > block:
        temporary.extend(_run_batched(settings, pages, block, use_cache=use_cache))
    else:
        artifacts_dir = convert_pdf_to_markdown(
            settings.input_pdf,
            settings.temp_md,
            ocr=settings.ocr,
            images_scale=settings.images_scale,
            image_sanitize=settings.image_sanitize,
            max_workers=settings.max_workers,
        )
        process_markdown_with_ai(
            settings.temp_md, settings.temp_clean_md, settings, use_cache=use_cache
        )
        temporary.append(artifacts_dir)

    convert_markdown_to_pdf(settings.temp_clean_md, settings.output_pdf, settings.pdf_engine)

    if keep_temp:
        print("[4/4] Behalte temporäre Zwischendateien (--keep-temp).")
    else:
        clean_temporary_files(temporary)

    print(f"-> Gesamtdauer: {_format_duration(time.perf_counter() - started)}")
