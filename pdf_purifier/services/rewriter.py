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

import hashlib
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

from pdf_purifier.config import Settings
from pdf_purifier.prompts import SYSTEM_PROMPT


class RewritingError(RuntimeError):
    """Fataler Fehler - bricht den Lauf ab (z. B. falscher Key)."""


class ChunkRewriteError(RuntimeError):
    """Ein einzelner Chunk scheiterte; der Originaltext wird übernommen."""


#: HTTP-Status, bei denen ein erneuter Versuch sinnvoll ist.
_RETRY_STATUS = {408, 429, 500, 502, 503, 504}


# --- Blöcke, die die KI niemals zu sehen bekommt ---------------------------

#: Marker, der einen geschützten Block im Prompt ersetzt.
_MARKER_TEMPLATE = "[[B{}]]"
_MARKER_RE = re.compile(r"\[\[B(\d+)\]\]")
_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s")
_FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")
# Bild, optional mit Größenangabe: ![Image](pfad.png){width=63.5mm}
_IMAGE_RE = re.compile(r"^\s*!\[[^\]]*\]\([^)]+\)(\{[^}]*\})?\s*$")
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
    attempts = max(1, settings.api_retries)
    last_error: object = None

    for attempt in range(1, attempts + 1):
        try:
            response = requests.post(
                settings.deepseek_url,
                headers=headers,
                json=payload,
                timeout=settings.request_timeout,
            )
        except requests.RequestException as exc:
            last_error = exc
        else:
            if response.status_code in (401, 403, 404):
                raise RewritingError(
                    f"\n[Fehler] DeepSeek hat die Anfrage abgelehnt (HTTP {response.status_code}).\n"
                    f"   Aufgerufene URL : {settings.deepseek_url}\n"
                    f"   Modell          : {settings.model_name}\n"
                    "   Prüfe DEEPSEEK_URL (vollständiger API-Endpunkt, z. B. "
                    "https://api.deepseek.com/chat/completions), DEEPSEEK_API_KEY und MODEL_NAME."
                )
            if response.status_code not in _RETRY_STATUS:
                response.raise_for_status()
                return response.json()["choices"][0]["message"]["content"].strip()
            last_error = f"HTTP {response.status_code}"

        if attempt < attempts:
            # 2, 4, 8 ... Sekunden, höchstens 10.
            time.sleep(min(2**attempt, 10))

    raise ChunkRewriteError(
        f"nach {attempts} Versuchen fehlgeschlagen ({last_error})"
    )


def _cache_file(settings: Settings) -> Path:
    """Pfad zum Antwort-Cache (macht Wiederholungsläufe kostenlos)."""
    return Path(settings.project_root) / ".pdf_purifier_cache.json"


def _load_cache(settings: Settings) -> dict[str, str]:
    """Lädt bereits bezahlte API-Antworten."""
    try:
        data = json.loads(_cache_file(settings).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_cache(settings: Settings, cache: dict[str, str]) -> None:
    """Schreibt den Antwort-Cache zurück."""
    try:
        _cache_file(settings).write_text(
            json.dumps(cache, ensure_ascii=False), encoding="utf-8"
        )
    except OSError:
        pass


def _cache_key(prompt_text: str, settings: Settings) -> str:
    """Eindeutiger Schlüssel aus Modell + Prompt."""
    payload = f"{settings.model_name}\x00{prompt_text}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _rewrite_chunk(
    chunk: list[str],
    settings: Settings,
    cache: dict[str, str],
    use_cache: bool,
) -> tuple[str | None, str]:
    """Maskiert, fragt die API und setzt die Marker zurück.

    Gibt ``(text, "")`` bei Erfolg zurück, sonst ``(None, grund)``.
    """
    prompt_text, masked = mask_blocks(chunk)
    key = _cache_key(prompt_text, settings)

    answer = cache.get(key) if use_cache else None
    if answer is None:
        answer = query_deepseek(prompt_text, settings)  # kann RewritingError werfen
        # Immer merken - auch bei --no-cache; das Flag steuert nur das Lesen.
        cache[key] = answer

    restored = unmask_blocks(answer, masked)
    if restored is None:
        return None, "Marker verändert"
    return restored, ""


def process_markdown_with_ai(
    input_md: str | Path,
    output_md: str | Path,
    settings: Settings,
    *,
    use_cache: bool = True,
) -> None:
    """Verarbeitet das Markdown block- und strukturweise und schreibt das Ergebnis.

    Die Chunks sind unabhängig voneinander und werden deshalb parallel an die
    API geschickt - aus n Wartezeiten wird so eine.
    """
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
    workers = max(1, min(settings.max_workers, total))

    cache = _load_cache(settings) if use_cache else {}
    cached = 0
    if use_cache:
        cached = sum(
            1
            for chunk in chunks
            if _cache_key(mask_blocks(chunk)[0], settings) in cache
        )

    print(
        f"-> {len(blocks)} Blöcke (davon {protected} geschützt) auf {total} Chunks "
        f"verteilt, {workers} parallel"
        + (f", {cached} aus dem Cache" if cached else "")
        + "."
    )

    results: dict[int, str] = {}
    problems: list[str] = []
    fatal: RewritingError | None = None

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_rewrite_chunk, chunk, settings, cache, use_cache): index
            for index, chunk in enumerate(chunks)
        }
        finished = 0
        for future in as_completed(futures):
            index = futures[future]
            finished += 1
            print(f"   {finished}/{total} Chunks fertig...", end="\r")
            try:
                text, note = future.result()
            except RewritingError as exc:
                fatal = fatal or exc
                text, note = None, str(exc)
            except Exception as exc:  # noqa: BLE001 - Verbindungsfehler
                text, note = None, str(exc)

            if text is None:
                problems.append(f"Chunk {index + 1}: {note}")
                results[index] = "\n\n".join(chunks[index])
            else:
                results[index] = text

    print(" " * 40, end="\r")

    if fatal is not None:
        raise fatal
    if problems and len(problems) == total:
        raise RewritingError(
            "\n[Fehler] Kein einziger Chunk konnte umgeschrieben werden. Die Ausgabe wäre "
            "nur eine Kopie des Originals. Bitte DEEPSEEK_URL, API-Key und MODEL_NAME prüfen."
        )

    # Immer speichern - auch bei --no-cache, damit der nächste Lauf davon profitiert.
    _save_cache(settings, cache)

    output_md = Path(output_md)
    with output_md.open("w", encoding="utf-8") as handle:
        for index in range(total):
            handle.write(results[index] + "\n\n")

    for problem in problems:
        print(f"[Warnung] {problem} - Originaltext wird übernommen.")

    print(f"\n-> Umschreibung abgeschlossen. Bereinigtes Markdown in '{output_md}' gespeichert.")
