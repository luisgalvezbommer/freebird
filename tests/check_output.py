"""Endkontrolle: steckt noch eine Käufer-Identität im Ergebnis?

Warum nicht einfach ``grep hotmail``?
--------------------------------------
``hotmail`` allein ist als Prüfmuster **unbrauchbar**: Ein IT-Lehrbuch nennt
Freemail-Anbieter wie Google Mail, GMX oder Hotmail im Fließtext. Genau solche
Zeilen hat eine frühere, zu grobe Redaktions-Regel gelöscht - also echter
Lehrinhalt. Deshalb wird hier mit **exakten** Merkmalen der konkreten
personalen Kennzeichnung geprüft.

Was geprüft wird
----------------
1. Die Blockdateien unter ``.pdf_purifier_parts/``.
2. Der Textstrom des fertigen PDF (via ``pdftotext``) - seitenweise, damit
   der Fundort benannt werden kann.
3. Randdaten: Seitenzahl, Producer.

Aufruf::

    .venv/bin/python tests/check_output.py [pfad/zur/datei.pdf]

Rückgabewert 0 = sauber, 1 = Identität gefunden.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

#: Exakte Merkmale der personalisierten Kennzeichnung dieses Exemplars.
#: Bewusst NICHT dabei: "hotmail", "exemplar", "lizenz" - das sind normale Wörter
#: eines IT-Lehrbuchs.
FORBIDDEN = (
    r"galvez",
    r"gal531026",
    r"jg3b-5ytq",
    r"manuel\s+arturo",
)

_PATTERN = re.compile("|".join(FORBIDDEN), re.IGNORECASE)


def _check_parts() -> int:
    parts = PROJECT_ROOT / ".pdf_purifier_parts"
    if not parts.is_dir():
        print("-> keine Blockdateien vorhanden (uebersprungen)")
        return 0

    hits = 0
    files = sorted(parts.rglob("part_*.md"))
    for path in files:
        for index, line in enumerate(
            path.read_text(encoding="utf-8", errors="replace").splitlines(), 1
        ):
            if _PATTERN.search(line):
                hits += 1
                print(f"   {path.relative_to(parts.parent)}:{index}: {line.strip()[:160]}")
    print(f"-> {len(files)} Blockdatei(en) geprueft, {hits} Treffer")
    return hits


def _check_pdf(pdf_path: Path) -> int:
    if not pdf_path.is_file():
        print(f"-> '{pdf_path}' existiert nicht")
        return 1

    result = subprocess.run(
        ["pdftotext", str(pdf_path), "-"],
        capture_output=True,
        text=True,
        check=True,
    )
    pages = result.stdout.split("\f")

    hits = 0
    for page_number, page_text in enumerate(pages, 1):
        for line in page_text.splitlines():
            if _PATTERN.search(line):
                hits += 1
                print(f"   Seite {page_number}: {line.strip()[:200]}")

    size_mb = pdf_path.stat().st_size / 1024 / 1024
    print(f"-> {len(pages)} Seiten im Textstrom, {size_mb:.1f} MB, {hits} Treffer")
    return hits


def _report_info(pdf_path: Path) -> None:
    if not pdf_path.is_file():
        return
    info = subprocess.run(
        ["pdfinfo", str(pdf_path)], capture_output=True, text=True, check=True
    ).stdout
    for key in ("Title", "Pages", "Page size", "Producer", "Creator"):
        for line in info.splitlines():
            if line.startswith(f"{key}:"):
                print(f"   {line.strip()}")


def main() -> int:
    pdf_path = Path(sys.argv[1]) if len(sys.argv) > 1 else PROJECT_ROOT / "IT-Handbuch_bereinigt.pdf"

    print("=== 1. BLOCKDATEIEN ===")
    part_hits = _check_parts()

    print()
    print("=== 2. FERTIGES PDF ===")
    print(f"   Datei: {pdf_path.name}")
    _report_info(pdf_path)
    pdf_hits = _check_pdf(pdf_path)

    print()
    print("=== 3. ERGEBNIS ===")
    if part_hits or pdf_hits:
        print(f"FEHLER - Identitaet noch vorhanden ({part_hits} + {pdf_hits} Treffer).")
        return 1
    print("OK - keine Identitaet der kaufenden Person gefunden.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
