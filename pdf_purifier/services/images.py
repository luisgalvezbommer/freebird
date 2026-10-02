"""Bereinigt die aus dem PDF extrahierten Bilder - parallel.

Ein PDF kann Wasserzeichen *in Bildern* tragen:

* Metadaten (EXIF, XMP, IPTC, C2PA/"Content Credentials")
* LSB-Steganografie in den Pixelwerten

``metadata``  entfernt ersteres - verlustfrei, daher der Standard.
``reencode``  kodiert zusätzlich als JPEG neu und zerstört damit LSB-Daten;
              das kostet Bildqualität, deshalb muss man es ausdrücklich wollen.

Robuste Wasserzeichen (Digimarc-/SynthID-Art) überstehen beides - sie sind mit
Python nicht entfernbar. Sichtbare Logos auf dem Bild bräuchten Inpainting mit
einer Maske und sind nicht automatisch lösbar.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image

#: Erlaubte Betriebsarten.
MODES = ("off", "metadata", "reencode")
_JPEG_QUALITY = 85
_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp"}


def _clean_image(source: Path, mode: str) -> tuple[str, str] | None:
    """Bereinigt ein einzelnes Bild.

    Gibt ``(alter_name, neuer_name)`` zurück, wenn sich der Dateiname ändert.
    """
    with Image.open(source) as image:
        # Neu aufbauen statt kopieren: dabei fallen EXIF, XMP und ICC weg.
        cleaned = Image.new(image.mode, image.size)
        cleaned.putdata(list(image.getdata()))

        if mode == "reencode":
            target = source.with_suffix(".jpg")
            cleaned.convert("RGB").save(target, "JPEG", quality=_JPEG_QUALITY)
            if target != source:
                source.unlink(missing_ok=True)
                return source.name, target.name
            return None

        cleaned.save(source, "PNG")
    return None


def sanitize_images(
    artifacts_dir: str | Path | None,
    *,
    mode: str = "metadata",
    workers: int = 4,
) -> dict[str, str]:
    """Bereinigt alle Bilder in ``artifacts_dir`` parallel.

    Gibt eine Umbenennungs-Tabelle ``{alter_name: neuer_name}`` zurück, damit
    der Aufrufer die Verweise im Markdown anpassen kann.
    """
    if mode not in MODES or mode == "off" or artifacts_dir is None:
        return {}

    directory = Path(artifacts_dir)
    if not directory.is_dir():
        return {}

    files = sorted(
        path for path in directory.iterdir() if path.is_file() and path.suffix.lower() in _SUFFIXES
    )
    if not files:
        return {}

    renames: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(files)))) as pool:
        for result in pool.map(lambda path: _clean_image(path, mode), files):
            if result is not None:
                old_name, new_name = result
                renames[old_name] = new_name

    verb = "neu kodiert" if mode == "reencode" else "Metadaten entfernt"
    print(f"-> {len(files)} Bild(er) bereinigt ({verb}).")
    return renames
