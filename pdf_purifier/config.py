"""Konfiguration: lädt alle Einstellungen aus der ``.env``-Datei.

Alle Werte, die früher als Konstanten oben in ``template.py``/``main.py``
standen, kommen jetzt aus Umgebungsvariablen (bzw. der ``.env``-Datei). Die
Standardwerte entsprechen exakt dem alten Verhalten.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path

from dotenv import load_dotenv

# Projektwurzel = Ordner, der das Package und die .env-Datei enthält.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ENV_FILE = PROJECT_ROOT / ".env"

# Werte, die als "nicht gesetzt" gelten (Platzhalter aus .env.example / template.py).
_PLACEHOLDER_API_KEYS = {
    "",
    "sk-dein-echter-api-key-hier",
    "sk-dein-echter-deepseek-key-hier",
}


def _get(name: str, default: str) -> str:
    """Liest eine Textvariable und fällt bei leerem Wert auf ``default`` zurück."""
    value = os.getenv(name)
    return value if value not in (None, "") else default


def _get_int(name: str, default: int) -> int:
    """Liest eine Ganzzahlvariable und fällt bei leerem Wert auf ``default`` zurück."""
    raw = os.getenv(name)
    if raw in (None, ""):
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(
            f"Die Umgebungsvariable {name!r} muss eine ganze Zahl sein, ist aber {raw!r}."
        ) from exc


def _get_float(name: str, default: float) -> float:
    """Liest eine Gleitkommazahl und fällt bei leerem Wert auf ``default`` zurück."""
    raw = os.getenv(name)
    if raw in (None, ""):
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(
            f"Die Umgebungsvariable {name!r} muss eine Zahl sein, ist aber {raw!r}."
        ) from exc


def _get_choice(name: str, default: str, allowed: set[str]) -> str:
    """Liest eine Auswahlvariable; unbekannte Werte fallen auf ``default`` zurück."""
    value = _get(name, default).strip().lower()
    return value if value in allowed else default


def _resolve(root: Path, value: str) -> Path:
    """Macht einen Pfad absolut, relativ zur Projektwurzel."""
    path = Path(value).expanduser()
    return path if path.is_absolute() else (root / path)


@dataclass(frozen=True)
class Settings:
    """Unveränderliche Sammlung aller Laufzeit-Einstellungen."""

    deepseek_api_key: str
    deepseek_url: str
    model_name: str
    input_pdf: Path
    output_pdf: Path
    temp_md: Path
    temp_clean_md: Path
    max_paragraphs_per_chunk: int
    max_chars_per_chunk: int
    request_timeout: int
    ocr: str
    images_scale: float
    image_sanitize: str
    max_workers: int
    pdf_engine: str
    project_root: Path

    @property
    def has_api_key(self) -> bool:
        """True, wenn ein echter (kein Platzhalter-)API-Key gesetzt ist."""
        return self.deepseek_api_key.strip() not in _PLACEHOLDER_API_KEYS

    @classmethod
    def from_env(
        cls,
        env_file: str | Path | None = None,
        *,
        override: bool = False,
    ) -> "Settings":
        """Lädt die ``.env``-Datei und baut daraus ein ``Settings``-Objekt."""
        load_dotenv(dotenv_path=env_file or DEFAULT_ENV_FILE, override=override)
        root = PROJECT_ROOT
        return cls(
            deepseek_api_key=_get("DEEPSEEK_API_KEY", ""),
            deepseek_url=_get("DEEPSEEK_URL", "https://api.deepseek.com/chat/completions"),
            model_name=_get("MODEL_NAME", "deepseek-chat"),
            input_pdf=_resolve(root, _get("INPUT_PDF", "kauf_datei.pdf")),
            output_pdf=_resolve(root, _get("OUTPUT_PDF", "sauberes_buch.pdf")),
            temp_md=_resolve(root, _get("TEMP_MD", "temp_extracted.md")),
            temp_clean_md=_resolve(root, _get("TEMP_CLEAN_MD", "temp_cleaned.md")),
            max_paragraphs_per_chunk=_get_int("MAX_PARAGRAPHS_PER_CHUNK", 8),
            max_chars_per_chunk=_get_int("MAX_CHARS_PER_CHUNK", 4000),
            request_timeout=_get_int("REQUEST_TIMEOUT", 60),
            ocr=_get_choice("OCR", "auto", {"auto", "on", "off"}),
            images_scale=_get_float("IMAGES_SCALE", 3.0),
            image_sanitize=_get_choice(
                "IMAGE_SANITIZE", "metadata", {"off", "metadata", "reencode"}
            ),
            max_workers=_get_int("MAX_WORKERS", 4),
            pdf_engine=_get("PDF_ENGINE", "weasyprint"),
            project_root=root,
        )

    def with_overrides(self, **changes: object) -> "Settings":
        """Erzeugt eine Kopie mit geänderten Feldern (z. B. aus CLI-Argumenten)."""
        return replace(self, **changes)
