"""Schritt 4: Löscht die temporären Zwischendateien und extrahierten Bilder."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Iterable


def clean_temporary_files(paths: Iterable[str | Path | None]) -> None:
    """Entfernt alle existierenden Dateien und Verzeichnisse aus ``paths``."""
    print("[4/4] Bereinige temporäre Zwischendateien...")
    for path in paths:
        if path is None:
            continue
        candidate = Path(path)
        if candidate.is_dir():
            # Die von Docling extrahierten Bilder liegen in einem eigenen Ordner.
            shutil.rmtree(candidate, ignore_errors=True)
        elif candidate.exists():
            candidate.unlink()
    print("-> Alle temporären Dateien entfernt. Prozess erfolgreich beendet!")
