"""Entfernt personalisierte Kopie-Kennzeichnungen ("Wasserzeichen") aus dem Text.

Viele gekaufte PDFs tragen eine Kennzeichnung wie diese::

    Exemplar Nr. jg3b-5ytq-eu6i-axr4 zum persönlichen Gebrauch für
    Manuel Arturo Galvez Estrada, gal531026@hotmail.com

Das ist der stärkste Identitätsmarker im ganzen Dokument - und der KI-Prompt
würde ihn sogar *schützen*, weil er Eigennamen erhalten soll. Deshalb muss er
VOR der Umschreibung verschwinden.

Vorgehen: Eine Kennzeichnung wird **absatzweise** entfernt - aber nur, wenn der
Absatz eine eindeutige Kennzeichnungs-Formulierung enthält (siehe ANCHORS).
Der ganze Absatz verschwindet, damit auch die umgebrochene Fortsetzungszeile
mit Name und E-Mail mitkommt.

Wichtig: Es wird NICHT auf E-Mail-Adressen allein reagiert und NICHT auf
algemeine Wörter wie "Bestellnummer", "Lizenz für" oder "licensed to".
Dieses Dokument ist ein Lehrbuch: Es enthält Beispiel-E-Mails,
Beispiel-Datensätze und Sätze über Lizenzen. Eine frühere Fassung dieses
Moduls hat genau solche Zeilen gelöscht und damit Lehrinhalt vernichtet.

Gelöscht wird deshalb nur, wenn der Absatz zusätzlich ein Identitätsmerkmal
enthält: eine E-Mail-Adresse oder eine maschinell erzeugte Kopie-Kennung wie
"jg3b-5ytq-eu6i-axr4". Enthält ein Absatz nur das Ankerwort (etwa "nur zum
persönlichen Gebrauch" in einem Urheberrechtshinweis), bleibt er stehen und
wird zur Prüfung gemeldet.

Entfernte und gemeldete Zeilen werden vollständig ausgegeben, damit nichts
unbemerkt verschwindet.
"""

from __future__ import annotations

import re
from typing import NamedTuple

#: Formulierungen, die auf eine personalisierte Kopie-Kennzeichnung hindeuten.
#: Bewusst eng gefasst: Diese Wendungen stehen nicht als Fließtext in
#: Fachliteratur - sie stammen von Kopierschutz-Stempeln.
ANCHORS = (
    "exemplar nr",
    "exemplar-nr",
    "exemplarnummer",
    "persönliches exemplar",
    "persoenliches exemplar",
    "zum persönlichen gebrauch",
    "zum persoenlichen gebrauch",
    "personal copy",
)

_ANCHOR_RE = re.compile("|".join(re.escape(a) for a in ANCHORS), re.IGNORECASE)
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")

#: Sicherheitsbremse: Ein Absatz, der länger ist als das, wird nicht komplett
#: gelöscht - dann fliegen nur die Ankerzeile und direkt folgende Zeilen mit
#: E-Mail-Adresse. Verhindert, dass ein Fehlalarm einen ganzen Lehrtext frisst.
_MAX_PARAGRAPH_LINES = 6

#: Obergrenze für die Länge einer gemeldeten Zeile.
_REPORT_WIDTH = 200

#: Maschinell erzeugte Kopie-Kennung, z. B. "jg3b-5ytq-eu6i-axr4".
_COPY_ID_RE = re.compile(r"\b[0-9a-z]{4}(?:-[0-9a-z]{4}){2,}\b", re.IGNORECASE)


def _has_identity(text: str) -> bool:
    """Prüft, ob der Text eine konkrete Person oder Kopie identifiziert."""
    return bool(_EMAIL_RE.search(text) or _COPY_ID_RE.search(text))


class RedactionResult(NamedTuple):
    """Ergebnis der Bereinigung.

    ``text``    - bereinigter Text
    ``removed`` - gelöschte Zeilen (Kennzeichnung inkl. Identitätsmerkmal)
    ``review``  - nicht gelöschte Ankerzeilen ohne Identitätsmerkmal
    """

    text: str
    removed: list[str]
    review: list[str]


def _paragraph_bounds(lines: list[str], index: int) -> tuple[int, int]:
    """Anfang und Ende des Absatzes um *index* (Zeilen bis zur Leerzeile)."""
    start = index
    while start > 0 and lines[start - 1].strip():
        start -= 1
    end = index
    while end + 1 < len(lines) and lines[end + 1].strip():
        end += 1
    return start, end


def _removal_span(lines: list[str], index: int) -> tuple[int, int]:
    """Absatzgrenzen um *index*, begrenzt durch ``_MAX_PARAGRAPH_LINES``."""
    start, end = _paragraph_bounds(lines, index)
    if end - start + 1 <= _MAX_PARAGRAPH_LINES:
        return start, end

    end = index
    while (
        end + 1 < len(lines)
        and lines[end + 1].strip()
        and _EMAIL_RE.search(lines[end + 1])
        and end + 1 - index < _MAX_PARAGRAPH_LINES
    ):
        end += 1
    return index, end


def redact_personal_data(markdown: str) -> RedactionResult:
    """Entfernt Absätze mit personalisierter Kopie-Kennzeichnung."""
    lines = markdown.splitlines()
    keep = [True] * len(lines)
    removed: list[str] = []
    review: list[str] = []

    for index, line in enumerate(lines):
        if not keep[index] or not _ANCHOR_RE.search(line):
            continue

        start, end = _removal_span(lines, index)
        if not _has_identity("\n".join(lines[start : end + 1])):
            # Ankerwort ohne Identitätsmerkmal - kann Fließtext sein (etwa
            # "nur zum persönlichen Gebrauch" im Urheberrechtshinweis).
            # Nicht löschen, sondern zur Prüfung melden.
            review.append(lines[index].strip()[:_REPORT_WIDTH])
            continue

        for position in range(start, end + 1):
            if keep[position]:
                keep[position] = False
                removed.append(lines[position].strip()[:_REPORT_WIDTH])

    kept = [line for line, keep_it in zip(lines, keep) if keep_it]
    return RedactionResult("\n".join(kept), removed, review)


def print_report(result: RedactionResult) -> None:
    """Meldet vollständig, was entfernt und was zur Prüfung gemeldet wurde."""
    if result.removed:
        print(f"-> {len(result.removed)} Zeile(n) mit Kopie-Kennzeichnung entfernt:")
        for line in result.removed:
            print(f"     {line!r}")
    if result.review:
        print(f"-> ACHTUNG: {len(result.review)} Zeile(n) mit Kennzeichnungs-Wortlaut,")
        print("   aber ohne Identitätsmerkmal. NICHT gelöscht - bitte prüfen:")
        for line in result.review:
            print(f"     {line!r}")
