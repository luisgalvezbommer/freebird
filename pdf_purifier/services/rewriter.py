"""Schritt 2: Strukturbewusstes Chunking und Umschreiben über die DeepSeek-API.

Warum nicht einfach an Absätzen trennen?
----------------------------------------
Das frühere Verfahren zerlegte den Text stumpf in 4-Absatz-Blöcke. Bildverweise,
Tabellen und Codeblöcke konnten dadurch mitten aus ihrem Zusammenhang gerissen
werden, und die KI durfte sie "leicht umformulieren" - Bilder gingen verloren
oder landeten an der falschen Stelle.

Jetzt gilt:

* Blöcke werden nie zerschnitten; bevorzugt wird an Überschriften getrennt.
* Bilder, Tabellen, Codeblöcke und HTML sieht die KI **gar nicht**. Sie werden
  durch Marker wie ``[[B2]]`` ersetzt und danach unverändert an exakt derselben
  Position wieder eingesetzt.
* Fehlt nach der Antwort auch nur ein Marker (oder ist die Reihenfolge kaputt),
  wird der Chunk verworfen und unverändert übernommen. Es geht nie Inhalt
  verloren - im schlimmsten Fall bleibt ein Chunk unformuliert.
"""

from __future__ import annotations

import re
from pathlib import Path

import requests

from pdf_purifier.config import Settings
from pdf_purifier.prompts import SYSTEM_PROMPT


class RewritingError(RuntimeError):
    """Wird ausgelöst, wenn die Eingabe-Datei fehlt oder nicht lesbar ist."""


# --- Blöcke, die die KI niemals zu sehen bekommt ---------------------------

#: Marker, der einen geschützten Block im Prompt ersetzt.
_MARKER_TEMPLATE = "[[B{}]]"
_MARKER_RE = re.compile(r"\[\[B(\d+)\]\]")
_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s")
_FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")
_IMAGE_RE = re.compile(r"^\s*!\[[^\]]*\]\([^)]+\)\s*$")
_TABLE_ROW_RE = re.compile(r"^\s*\|.*\|\s*$")
_TABLE_SEP_RE = re.compile(r"^\s*\|?[\s:|_-]*-[\s:|-]*\|")
_HTML_RE = re.compile(
    r"^\s*<(!--|/?(div|table|figure|img|section|hr|br)\b)", re.IGNORECASE
)


def split_blocks(markdown: str) -> list[str]:
    """Zerlegt Markdown in Blöcke (Leerzeilen trennen), ohne Codezäune zu zerschneiden."""
    blocks: list[str] = []
    buffer: list[str] = []
    in_fence = False
    fence_token = ""

    for line in markdown.splitlines():
        fence = _FENCE_RE.match(line)
        if fence:
            token = fence.group(1)
            if not in_fence:
                in_fence, fence_token = True, token
            elif token[0] == fence_token[0] and len(token) >= len(fence_token):
                in_fence = False
            buffer.append(line)
            continue

        if not in_fence and not line.strip():
            if buffer:
                blocks.append("\n".join(buffer))
                buffer = []
            continue

        buffer.append(line)

    if buffer:
        blocks.append("\n".join(buffer))
    return blocks


def is_protected(block: str) -> bool:
    """True, wenn der Block unverändert bleiben muss (Bild, Tabelle, Code, HTML)."""
    lines = [line for line in block.splitlines() if line.strip()]
    if not lines:
        return True
    if _FENCE_RE.match(lines[0]):
        return True
    if any(_IMAGE_RE.match(line) for line in lines):
        return True
    if _HTML_RE.match(lines[0]):
        return True

    rows = sum(1 for line in lines if _TABLE_ROW_RE.match(line))
    if rows >= 2 or (rows and any(_TABLE_SEP_RE.match(line) for line in lines)):
        return True
    return False


def build_chunks(
    blocks: list[str],
    *,
    max_chars: int,
    max_blocks: int,
) -> list[list[str]]:
    """Bündelt Blöcke zu Chunks - bevorzugt an Überschriften, nie mitten im Block."""
    chunks: list[list[str]] = []
    current: list[str] = []
    size = 0

    for block in blocks:
        is_heading = bool(_HEADING_RE.match(block))
        is_full = size + len(block) > max_chars or len(current) >= max_blocks
        if current and (is_full or is_heading):
            chunks.append(current)
            current, size = [], 0
        current.append(block)
        size += len(block) + 2

    if current:
        chunks.append(current)
    return chunks


def mask_blocks(blocks: list[str]) -> tuple[str, dict[str, str]]:
    """Ersetzt geschützte Blöcke durch Marker.

    Gibt den Text für die KI und die Zuordnung Marker -> Originalblock zurück.
    """
    parts: list[str] = []
    masked: dict[str, str] = {}

    for index, block in enumerate(blocks):
        if is_protected(block):
            marker = _MARKER_TEMPLATE.format(index)
            masked[marker] = block
            parts.append(marker)
        else:
            parts.append(block)

    return "\n\n".join(parts), masked


def unmask_blocks(text: str, masked: dict[str, str]) -> str | None:
    """Setzt die Marker zurück.

    Gibt ``None`` zurück, wenn Marker fehlen, dazugekommen oder vertauscht sind -
    dann darf das Ergebnis nicht verwendet werden.
    """
    found = [f"[[B{index}]]" for index in _MARKER_RE.findall(text)]
    if found != list(masked):
        return None

    for marker, original in masked.items():
        text = text.replace(marker, original)
    return text


def query_deepseek(text_chunk: str, settings: Settings) -> str:
    """Sendet einen Textblock an die DeepSeek-API.

    Hebt :class:`RewritingError` hervor, wenn der Endpunkt oder der Key nicht
    stimmt. Früher wurde in diesem Fall stillschweigend der Originaltext
    verwendet - die "Bereinigung" lief dann ins Leere, ohne dass es auffiel.
    """
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {settings.deepseek_api_key}",
    }
    payload = {
        "model": settings.model_name,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Hier ist der Text zum Umformulieren:\n\n{text_chunk}"},
        ],
        "stream": False,
        "temperature": 0.3,  # niedrig halten, damit der Inhalt treu bleibt
    }
    response = requests.post(
        settings.deepseek_url,
        headers=headers,
        json=payload,
        timeout=settings.request_timeout,
    )

    if response.status_code in (401, 403, 404):
        raise RewritingError(
            f"\n[Fehler] DeepSeek hat die Anfrage abgelehnt (HTTP {response.status_code}).\n"
            f"   Aufgerufene URL : {settings.deepseek_url}\n"
            f"   Modell          : {settings.model_name}\n"
            "   Prüfe DEEPSEEK_URL (vollständiger API-Endpunkt, z. B. "
            "https://api.deepseek.com/chat/completions), DEEPSEEK_API_KEY und MODEL_NAME."
        )

    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"].strip()


def process_markdown_with_ai(
    input_md: str | Path,
    output_md: str | Path,
    settings: Settings,
) -> None:
    """Verarbeitet das Markdown block- und strukturweise und schreibt das Ergebnis."""
    print("[2/4] Starte Text-Umschreibung mit DeepSeek API...")

    input_md = Path(input_md)
    if not input_md.exists():
        raise RewritingError(f"Fehler: Datei {input_md} wurde nicht gefunden.")

    content = input_md.read_text(encoding="utf-8")
    blocks = split_blocks(content)
    chunks = build_chunks(
        blocks,
        max_chars=settings.max_chars_per_chunk,
        max_blocks=settings.max_paragraphs_per_chunk,
    )
    total = len(chunks)
    protected = sum(1 for block in blocks if is_protected(block))
    print(
        f"-> {len(blocks)} Blöcke (davon {protected} geschützt) auf {total} Chunks "
        "verteilt. Sende Daten an Cloud..."
    )

    output_md = Path(output_md)
    output_md.write_text("", encoding="utf-8")

    unchanged = 0
    for index, chunk in enumerate(chunks, 1):
        print(f"   Verarbeite Häppchen {index}/{total}...", end="\r")
        prompt_text, masked = mask_blocks(chunk)

        result: str | None = None
        try:
            answer = query_deepseek(prompt_text, settings)
            result = unmask_blocks(answer, masked)
            if result is None:
                print(
                    f"\n[Warnung] Chunk {index}: KI hat Marker verändert - "
                    "Originaltext wird übernommen."
                )
        except RewritingError:
            raise
        except Exception as exc:  # noqa: BLE001 - Verbindungsfehler
            print(f"\n[Warnung] Chunk {index}: {exc} - Originaltext wird übernommen.")

        if result is None:
            unchanged += 1
            result = "\n\n".join(chunk)

        with output_md.open("a", encoding="utf-8") as handle:
            handle.write(result + "\n\n")

    if unchanged == total:
        raise RewritingError(
            "\n[Fehler] Kein einziger Chunk konnte umgeschrieben werden. Die Ausgabe wäre "
            "nur eine Kopie des Originals. Bitte DEEPSEEK_URL, API-Key und MODEL_NAME prüfen."
        )
    if unchanged:
        print(f"\n[Warnung] {unchanged} von {total} Chunks unverändert übernommen.")

    print(f"\n-> Umschreibung abgeschlossen. Bereinigtes Markdown in '{output_md}' gespeichert.")
